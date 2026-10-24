#!/usr/bin/env python3
"""Push Arsenal match updates to Tristan's Telegram while a game is on.

Runs once a minute from launchd and exits. No daemon to babysit: each run asks
"is there an Arsenal match in the window", and if there is, fetches the ESPN
summary once and sends anything it has not sent before.

Alerts, and deliberately nothing else:
  - the starting XI, the moment ESPN publishes it
  - kickoff
  - every goal, with scorer and minute
  - red cards
  - half time and full time

No yellow cards, no substitutions, no "kicking off soon" nagging.
Sent keys are recorded in kv_cache so a restart cannot double-send.

With config.LINEUP_TAKES on, the lineup alert also carries a Gooner take
(lineup_take.py). Claude can take two minutes and launchd never starts a run
while the last one is still going, so the take is written by a detached worker
(`live_alerts.py --lineup-take <job>`) and this run carries on with the goals.

Alerts go out as Telegram HTML so the take's bold renders: every alert is
escaped as it is built, and send() falls back to plain text if Telegram
refuses the markup.
"""

import html
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.expanduser("~/admin/scripts"))

import config  # noqa: E402
import db  # noqa: E402
import fixtures  # noqa: E402
import lineup_take  # noqa: E402
import matchcentre  # noqa: E402
from telegram_notify import MarkupRejected, notify  # noqa: E402

TEAM = "Arsenal"
WINDOW_BEFORE = timedelta(minutes=75)   # covers the lineup drop
WINDOW_AFTER = timedelta(minutes=180)   # covers stoppages and extra time
# A take still unsent this long after the lineup was claimed means its worker
# died: the next run sends the plain XI instead. Claude gets 120s of this.
TAKE_RESCUE_AFTER = timedelta(minutes=4)


def current_match(snap, now):
    """The one fixture worth polling right now, if any.

    A game in progress is in neither list: fixtures.assemble moves it to
    live_match. Missing that silenced every alert from the 22:30 refresh v
    Bayern on 2026-10-21, so the Rice equaliser and full time never went."""
    live = [snap["live_match"]] if snap.get("live_match") else []
    for e in live + (snap.get("fixtures") or []) + (snap.get("results") or []):
        try:
            ko = datetime.fromisoformat(e["kickoff"])
        except (KeyError, ValueError):
            continue
        if ko - WINDOW_BEFORE <= now <= ko + WINDOW_AFTER:
            return e
    return None


def sent_keys(conn, event_id):
    row = db.kv_get(conn, f"alerted:{event_id}")
    if not row or not row["value"]:
        return set()
    try:
        return set(json.loads(row["value"]))
    except json.JSONDecodeError:
        return set()


def remember(conn, event_id, keys):
    db.kv_set(conn, f"alerted:{event_id}", json.dumps(sorted(keys)),
              datetime.now(timezone.utc).isoformat())


def _scoreline(state):
    return f"{state['home']} {state['home_goals']}-{state['away_goals']} {state['away']}"


# The alerts speak as a Gooner watching with Tristan: they celebrate our goals, sulk at theirs,
# and gloat a bit at a red for the other lot. Each message picks its line from a few, seeded by
# match and alert, so a rerun sends the same words and two matches don't read the same.
LINES = {
    "lineup": ["👕 Team's in, Gooners. {formation} v {opp}:",
               "👕 Here's who's wearing the cannon v {opp} ({formation}):",
               "👕 XI's out. {formation} against {opp}:"],
    "ko": ["🔔 And we're off! Come on you Gunners! 🔴⚪",
           "🔔 Kick off. Ninety minutes, let's have it. COYG! 🔴⚪",
           "🔔 We're underway v {opp}. Up the Arsenal! 🔴⚪"],
    "goal": ["⚽ GET IIIN! {player}, {minute}! 🔴⚪",
             "⚽ YESSS! {player} {minute}! Get in there!",
             "⚽ GOOOAL! {player}, {minute}. Take a bow, son!",
             "⚽ {player}!!! {minute}. Ooh to be a Gooner 🎶"],
    "against": ["😤 Oh, for crying out loud. {opp} score, {player} {minute}.",
                "🙄 Typical. {player} for {opp}, {minute}.",
                "😩 Sloppy. {opp} have one, {player} {minute}."],
    "red_ours": ["🟥 You're joking. {player} sent off, {minute}. Down to ten, dig in lads.",
                 "🟥 Oh no. {player} walks, {minute}. Ten men, backs to the wall."],
    "red_theirs": ["🟥 Off you go! {player} sees red, {minute}. They're down to ten 😂",
                   "🟥 Ta-ra! {player} walks, {minute}. Ten men, let's have them."],
    "ht_ahead": ["⏸ Half time, and we're ahead. Keep it tight, lads.",
                 "⏸ Half time. In front. Forty-five more like that please."],
    "ht_level": ["⏸ Half time, all square. Need a bit more from us.",
                 "⏸ Half time, level. Come on Arsenal, step it up."],
    "ht_behind": ["⏸ Half time and we're behind. Big team talk needed.",
                  "⏸ Half time. Not good enough. We go again second half."],
    "ft_win": ["✅ FULL TIME! Job done. COYG! 🔴⚪",
               "✅ FULL TIME! Get in! Up the Arsenal! 🔴⚪"],
    "ft_draw": ["🤝 Full time. A point. We go again.",
                "🤝 Full time, honours even. Should've had more."],
    "ft_loss": ["💔 Full time. Gutted. We go again.",
                "💔 Full time. Not our day. Heads up, Gooners."],
}


def _line(event, key, kind, **fields):
    pick = random.Random(f"{event['id']}:{key}").choice(LINES[kind])
    return pick.format(**fields)


def _opponent(event):
    opp = event.get("opponent") or ""
    return "Spurs" if "Tottenham" in opp else opp


def _goals(state, home_is_us):
    ours = state["home_goals"] if home_is_us else state["away_goals"]
    theirs = state["away_goals"] if home_is_us else state["home_goals"]
    return ours or 0, theirs or 0


def _after_goal(state, home_is_us, is_ours):
    """A line under a goal: the chant when it's 1-0 to us, else the mood, which depends on who scored."""
    ours, theirs = _goals(state, home_is_us)
    if (ours, theirs) == (1, 0):
        return "1-0 to the Arsenal 🎶"
    if is_ours:
        return "In front! 🔥" if ours > theirs else "Level! Now go and win it." if ours == theirs else "Game on! Keep going."
    return "Still ahead. Nervy, but fine." if ours > theirs else "All square. Come on!" if ours == theirs else "We need a response."


def build_alerts(event, data, state, seen):
    """Everything that has happened and has not been sent yet."""
    out = []
    opp = _opponent(event)
    home_is_us = event["home"] == TEAM

    ars = matchcentre.arsenal_side(matchcentre._lineups(data))
    if ars and ars["published"] and "lineup" not in seen:
        xi = ", ".join(p["short"] or p["name"] for row in ars["rows"] for p in row)
        bench = ", ".join(p["short"] or p["name"] for p in ars["bench"])
        out.append(("lineup", f"{_line(event, 'lineup', 'lineup', formation=ars['formation'], opp=opp)}\n\n"
                              f"{xi}\n\nBench: {bench}"))

    if state:
        if state["state"] == "in" and "ko" not in seen:
            out.append(("ko", f"{_line(event, 'ko', 'ko', opp=opp)}\n{state['home']} v {state['away']}"))

        us_side = "home" if home_is_us else "away"
        tally = {"home": 0, "away": 0}
        for i, ev in enumerate(matchcentre._timeline(data)):
            if ev["scoring"] and ev["side"]:
                tally[ev["side"]] += 1
            if not ev["big"]:
                continue
            key = f"ev{i}"
            if key in seen:
                continue
            who = dict(player=ev["player"] or ev["text"], minute=ev["minute"], opp=opp)
            if ev["scoring"]:
                # The score as of this goal, counted off the goals themselves: ESPN's
                # scoreboard can trail its own goal feed (Eze's 25' v Bayern went out as 0-0, "Level!").
                at = dict(state, home_goals=tally["home"], away_goals=tally["away"]) if ev["side"] else state
                head = _line(event, key, "goal" if ev["ours"] else "against", **who)
                if ev["ours"] and ev["detail"]:
                    head += f"\nLovely ball from {ev['detail']}."
                out.append((key, f"{head}\n{_scoreline(at)}\n{_after_goal(at, home_is_us, ev['ours'])}"))
            else:
                kind = "red_ours" if ev["side"] == us_side else "red_theirs"
                out.append((key, f"{_line(event, key, kind, **who)}\n{_scoreline(state)}"))

        ours, theirs = _goals(state, home_is_us)
        mood = "ahead" if ours > theirs else "level" if ours == theirs else "behind"
        if state["name"] == "STATUS_HALFTIME" and "ht" not in seen:
            out.append(("ht", f"{_line(event, 'ht', f'ht_{mood}')}\n{_scoreline(state)}"))
        if state["completed"] and "ft" not in seen:
            if mood == "level" and "pen" in (state.get("detail") or "").lower():
                text = f"⏱ Full time: {_scoreline(state)}, settled on penalties ({state['detail']})."
            else:
                result = {"ahead": "ft_win", "level": "ft_draw", "behind": "ft_loss"}[mood]
                text = f"{_line(event, 'ft', result)}\n{_scoreline(state)}"
                if result == "ft_win" and opp == "Spurs":
                    text += "\nNorth London is RED 🔴⚪"
            out.append(("ft", text))

    # The templates carry no markup, so escaping the finished text escapes
    # every name in it: Telegram HTML only needs &, < and > replaced.
    return [(key, html.escape(text, quote=False)) for key, text in out]


def plain_text(text):
    """An alert as plain text: our only tags are <b>, and the rest is escaped."""
    return html.unescape(re.sub(r"</?b>", "", text))


def send(text):
    """Send one alert as HTML. If Telegram cannot parse it, the same alert goes
    again at once as plain text, so a stray character never costs an alert."""
    try:
        notify(text, parse_mode="HTML")
    except MarkupRejected as e:
        print(f"Telegram refused the HTML, resending plain: {e}")
        notify(plain_text(text))


def _take_key(event):
    return f"lineup_take:{event['id']}"


def _move(conn, key, old, new):
    """Move a lineup take from state `old` to `new` (None = not yet claimed).

    True for exactly one caller even when runs overlap, because the check and
    the write are one statement. Committed at once: get_conn() otherwise holds
    the write until its block ends."""
    now = datetime.now(timezone.utc).isoformat()
    if old is None:
        cur = conn.execute("INSERT INTO kv_cache (key, value, updated_at) VALUES (?, ?, ?) "
                           "ON CONFLICT(key) DO NOTHING", (key, new, now))
    else:
        cur = conn.execute("UPDATE kv_cache SET value = ?, updated_at = ? WHERE key = ? AND value = ?",
                           (new, now, key, old))
    conn.commit()
    return cur.rowcount == 1


def _send_claimed(conn, key, text):
    """Send a pending lineup unless someone else already is. pending -> sending
    -> sent; a failed send goes back to pending for the next run to rescue."""
    if not _move(conn, key, "pending", "sending"):
        return False
    try:
        send(text)
    except Exception:
        _move(conn, key, "sending", "pending")
        raise
    _move(conn, key, "sending", "sent")
    return True


def _spawn_take(event, data, plain):
    """Start the take worker in its own session, so launchd neither waits for
    it nor kills it when this run exits."""
    try:
        fd, path = tempfile.mkstemp(prefix="lineup-take-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"event": event, "data": data, "plain": plain}, f)
        here = os.path.dirname(os.path.abspath(__file__))
        subprocess.Popen([sys.executable, os.path.join(here, "live_alerts.py"), "--lineup-take", path],
                         stdin=subprocess.DEVNULL, cwd=here, start_new_session=True)
        return True
    except Exception:
        return False


def take_over_lineup(conn, event, data, alerts, seen):
    """Pull the plain lineup alert out of this run and hand it to a worker.

    The lineup key is claimed and recorded before anything slow, so neither an
    overlapping run nor the next one can send a second lineup. If the worker
    cannot start, or never reports back within TAKE_RESCUE_AFTER, the plain XI
    goes out from here instead: team news is never lost to a stuck Claude."""
    key = _take_key(event)
    rest = [(k, t) for k, t in alerts if k != "lineup"]
    plain = dict(alerts).get("lineup")
    if plain:
        seen.add("lineup")
        remember(conn, event["id"], seen)
        if _move(conn, key, None, "pending") and not _spawn_take(event, data, plain):
            _send_claimed(conn, key, plain)
        return rest

    row = db.kv_get(conn, key)
    if row and row["value"] == "pending":
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["updated_at"])
        if age > TAKE_RESCUE_AFTER:
            plain = dict(build_alerts(event, data, None, set())).get("lineup")
            if plain:
                _send_claimed(conn, key, plain)
    return rest


def deliver_lineup(job_path):
    """The worker: build the lineup message with its take and send it, unless
    a later run has already rescued it with the plain XI."""
    with open(job_path) as f:
        job = json.load(f)
    os.remove(job_path)
    event, plain = job["event"], job["plain"]
    try:
        text = lineup_take.message(event, job["data"], plain)
    except Exception as e:
        print(f"lineup take failed, sending the plain XI: {e!r}")
        text = plain
    with db.get_conn() as conn:
        if _send_claimed(conn, _take_key(event), text):
            print(f"sent lineup{' with take' if text != plain else ''} for {event['home']} v {event['away']}")


def _refresh_snapshot():
    try:
        import export
        export.main()
    except Exception:
        pass


def main():
    now = datetime.now(timezone.utc)
    with db.get_conn() as conn:
        snap = fixtures.get_cached(conn)
        if not snap:
            return
        event = current_match(snap, now)
        if not event or TEAM not in (event["home"], event["away"]):
            return

        try:
            data = matchcentre._get(
                matchcentre.SUMMARY.format(league=event.get("league") or "eng.1"),
                {"event": event["id"]})
        except Exception:
            return

        state = matchcentre.live_state(data)
        seen = sent_keys(conn, event["id"])
        alerts = build_alerts(event, data, state, seen)
        if config.LINEUP_TAKES:
            alerts = take_over_lineup(conn, event, data, alerts, seen)
        for key, text in alerts:
            send(text)
            seen.add(key)
        if alerts:
            remember(conn, event["id"], seen)
            print(f"sent {len(alerts)} alert(s) for {event['home']} v {event['away']}")

    # ESPN blocks browser user agents, so the phone reads match detail out of the
    # exported snapshot. While a game is on, refresh it every poll so the PWA is
    # never more than a minute behind.
    _refresh_snapshot()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--lineup-take"]:
        deliver_lineup(sys.argv[2])
    else:
        main()
