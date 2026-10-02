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
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.expanduser("~/admin/scripts"))

import db  # noqa: E402
import fixtures  # noqa: E402
import matchcentre  # noqa: E402
from telegram_notify import notify  # noqa: E402

TEAM = "Arsenal"
WINDOW_BEFORE = timedelta(minutes=75)   # covers the lineup drop
WINDOW_AFTER = timedelta(minutes=180)   # covers stoppages and extra time


def current_match(snap, now):
    """The one fixture worth polling right now, if any."""
    for e in (snap.get("fixtures") or []) + (snap.get("results") or []):
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


def build_alerts(event, data, state, seen):
    """Everything that has happened and has not been sent yet."""
    out = []

    ars = matchcentre.arsenal_side(matchcentre._lineups(data))
    if ars and ars["published"] and "lineup" not in seen:
        xi = ", ".join(p["short"] or p["name"] for row in ars["rows"] for p in row)
        bench = ", ".join(p["short"] or p["name"] for p in ars["bench"][:9])
        out.append(("lineup",
                    f"👕 Arsenal XI is out ({ars['formation']}) v {event['opponent']}\n\n"
                    f"{xi}\n\nBench: {bench}"))

    if state:
        if state["state"] == "in" and "ko" not in seen:
            out.append(("ko", f"🔔 Kick off: {state['home']} v {state['away']}"))

        for i, ev in enumerate(matchcentre._timeline(data)):
            if not ev["big"]:
                continue
            key = f"ev{i}"
            if key in seen:
                continue
            icon = "⚽" if ev["scoring"] else "🟥"
            out.append((key, f"{icon} {ev['minute']} {ev['text']}\n{_scoreline(state)}"))

        if state["name"] == "STATUS_HALFTIME" and "ht" not in seen:
            out.append(("ht", f"⏸ Half time: {_scoreline(state)}"))
        if state["completed"] and "ft" not in seen:
            out.append(("ft", f"⏱ Full time: {_scoreline(state)}"))

    return out


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
        for key, text in alerts:
            notify(text)
            seen.add(key)
        if alerts:
            remember(conn, event["id"], seen)
            print(f"sent {len(alerts)} alert(s) for {event['home']} v {event['away']}")

    # ESPN blocks browser user agents, so the phone reads match detail out of the
    # exported snapshot. While a game is on, refresh it every poll so the PWA is
    # never more than a minute behind.
    _refresh_snapshot()


if __name__ == "__main__":
    main()
