"""The Gooner take that rides under the lineup alert: what changed from the last
game and why, how we will set up, the opponent, what will work, a prediction.

Facts come only from ESPN (both XIs and benches, our previous match's XI, the
opponent's recent results) and the tracker's last 48 hours of news. The `claude`
CLI turns them into the take. The XI block above it is built in code, so a bad
take can never garble the team, and if Claude fails, errors, comes back empty or
takes longer than CLAUDE_TIMEOUT, the message falls back to the plain changes.

Preview a match without sending anything:
    ./venv/bin/python lineup_take.py <event_id> [--at 2026-10-24T13:02:00+00:00]
"""

import html
import json
import os
import pwd
import re
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import config
import db
import fixtures
import matchcentre

TEAM = "Arsenal"
CLAUDE_TIMEOUT = 120        # seconds; past this the XI goes out with the plain changes
MAX_TAKE_CHARS = 3000       # a take longer than this is a ramble, not a take
NEWS_HOURS = 48
FORM_GAMES = 5
SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{id}/schedule"

# Pre-match ESPN only says G/D/M/F. In every back four seen so far its slots are
# Opta's (2 right-back, 3 left-back, 5 and 6 the centre-backs; checked against the
# finished Bayern payload, which spells them out), and the take needs the
# full-backs to say who steps into midfield.
BACK_FOUR = {2: "RB", 3: "LB", 5: "CD-R", 6: "CD-L"}


def starters(side):
    return [p for row in side["rows"] for p in row]


def surname(p):
    return matchcentre.surname(p["short"] or p["name"])


def previous_match(snap, event):
    """Our last finished competitive match before this one (the snapshot holds
    competitive matches only, newest result first)."""
    return next((e for e in snap.get("results") or []
                 if e.get("finished") and str(e["id"]) != str(event["id"])
                 and e["kickoff"] < event["kickoff"]), None)


def changes(now, before):
    """Who came into the XI and who dropped out since the last game, by ESPN id."""
    now_xi, before_xi = starters(now), starters(before)
    now_ids, before_ids = {p["id"] for p in now_xi}, {p["id"] for p in before_xi}
    bench = {p["id"] for p in now["bench"]}
    return {
        "in": [p for p in now_xi if p["id"] not in before_ids],
        "out": [(p, "bench" if p["id"] in bench else "not in the squad")
                for p in before_xi if p["id"] not in now_ids],
        "formation": (before["formation"], now["formation"]),
    }


def describe(prev):
    """'the 2-2 at Bayern Munich', Arsenal's goals first."""
    home = prev["home"] == TEAM
    ours, theirs = (prev["home_goals"], prev["away_goals"]) if home else (prev["away_goals"], prev["home_goals"])
    return f"the {ours}-{theirs} {'v' if home else 'at'} {prev['opponent']}"


def changes_text(ch, prev):
    """The plain fallback: who's in, who's out, and any change of shape."""
    n = len(ch["in"])
    if not n:
        lines = [f"Same XI as {describe(prev)}."]
    else:
        lines = [f"{n} change{'s' if n > 1 else ''} from {describe(prev)}:",
                 "In: " + ", ".join(surname(p) for p in ch["in"]),
                 "Out: " + ", ".join(f"{surname(p)} ({why})" for p, why in ch["out"])]
    was, now = ch["formation"]
    if was and now and was != now:
        lines.append(f"Shape: {was} last time, {now} today.")
    return "\n".join(lines)


def _role(p, formation):
    if len(p["pos"]) > 1:
        return p["pos"]
    if formation.startswith("4") and p["place"] in BACK_FOUR:
        return BACK_FOUR[p["place"]]
    return p["pos"]


def _xi_line(side):
    return ", ".join(f"{p['name']} ({_role(p, side['formation'])})" for p in starters(side))


def _team_id(data, name):
    for r in data.get("rosters") or []:
        team = r.get("team") or {}
        if team.get("displayName") == name:
            return str(team.get("id") or "")
    return ""


def opponent_form(team_id, before):
    """The opponent's last few competitive results before kick-off, oldest first."""
    events = fixtures._get(SCHEDULE.format(id=team_id)).get("events") or []
    out = []
    for e in sorted(events, key=lambda e: e.get("date", "")):
        if "friendly" in (e.get("league") or {}).get("slug", ""):
            continue
        try:
            c = e["competitions"][0]
            ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            home = next(t for t in c["competitors"] if t["homeAway"] == "home")
            away = next(t for t in c["competitors"] if t["homeAway"] == "away")
        except (KeyError, IndexError, StopIteration, ValueError):
            continue
        if not (c.get("status") or {}).get("type", {}).get("completed") or ko >= before:
            continue
        hg, ag = fixtures._score(home.get("score")), fixtures._score(away.get("score"))
        us, them = (home, away) if str(home["team"].get("id")) == team_id else (away, home)
        ours, theirs = (hg, ag) if us is home else (ag, hg)
        if ours is None or theirs is None:
            continue
        result = "won" if ours > theirs else "lost" if ours < theirs else "drew"
        if ours == theirs and (us.get("winner") or them.get("winner")):
            result += ", won on penalties" if us.get("winner") else ", lost on penalties"
        comp = (e.get("league") or {}).get("abbreviation") or (e.get("league") or {}).get("name", "")
        out.append(f"{ko:%a %d %b}, {comp}: {home['team']['displayName']} {hg}-{ag} "
                   f"{away['team']['displayName']} ({result})")
    return out[-FORM_GAMES:]


def news(conn, names, now):
    """Tracker items from the last NEWS_HOURS: the Arsenal page plus anything
    naming the opponent. Nothing published after `now` (a preview of an old
    lineup must not read the match report)."""
    since = (now - timedelta(hours=NEWS_HOURS)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    until = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    like = " OR ".join("title LIKE ? OR summary LIKE ?" for _ in names)
    rows = conn.execute(
        f"""SELECT title, summary, source, published_at FROM items
            WHERE published_at >= ? AND published_at <= ? AND (page = 'arsenal' OR {like})
            ORDER BY published_at DESC""",
        [since, until] + [f"%{n}%" for n in names for _ in (0, 1)]).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["title"] in seen:
            continue
        seen.add(r["title"])
        when = datetime.fromisoformat(r["published_at"])
        summary = " ".join((r["summary"] or "").split())[:400]
        out.append(f"[{when:%a %d %b %H:%M} UTC, {r['source']}] {r['title']}. {summary}")
    return out


def gather(conn, event, data, now):
    """Every fact the take may use. Anything that fails to load is left out
    rather than guessed."""
    lineups = matchcentre._lineups(data)
    ours, theirs = matchcentre.arsenal_side(lineups), matchcentre.opponent_side(lineups)
    facts = {"ours": ours, "theirs": theirs, "prev": None, "prev_ours": None,
             "changes": None, "form": [], "news": []}

    prev = previous_match(fixtures.get_cached(conn) or {}, event)
    payload = matchcentre.get(conn, prev) if prev else None
    prev_ours = matchcentre.arsenal_side((payload or {}).get("lineups") or [])
    if prev_ours and prev_ours["published"]:
        facts.update(prev=prev, prev_ours=prev_ours, changes=changes(ours, prev_ours))

    opp = event.get("opponent") or (theirs or {}).get("team", "")
    try:
        team_id = _team_id(data, opp)
        facts["form"] = opponent_form(team_id, datetime.fromisoformat(event["kickoff"])) if team_id else []
    except Exception:
        facts["form"] = []

    names = sorted({n for n in (opp, event.get("opponent_name")) if n})
    facts["news"] = news(conn, names, now)
    return facts


VOICE = """You are a lifelong Arsenal fan texting your mate Tristan the moment the team news drops. Give him your take on today's line-up: warm, opinionated, a bit cheeky, a fellow Gooner with views, never a pundit reading a script."""

RULES = """RULES
1. The facts above are the only facts you may use. Your own football knowledge is out of date: players have moved clubs and managers have changed. If your memory disagrees with the facts, the facts win, and every player plays for the club the facts say.
2. Never state an injury, suspension, transfer, club, manager, stat or result that is not in the facts. If nothing in the facts explains why a player is out, do not invent a reason: call it rotation as your own guess, or just react to it.
3. Opinions on tactics are welcome and wanted: matchups, who steps where, what to fear.
4. Cover, in this order: what changed from the last game and why; how we will probably set up (for example which full-back steps into midfield when we have the ball); {opp}'s shape, recent form and who to watch; what will work against them; where it could bite us; then your score prediction as the very last line, Arsenal's goals first, written "I'm calling X-Y."
5. Do not repeat the XI or the bench as a list: they sit right above your take in the same message.
6. Format for a phone on Telegram: a first line that gives your verdict on the changes and ends with 🔴⚪, then "-" bullets of one or two short sentences each, then the "Where it could bite us:" line and the prediction line. About 8 to 11 lines and 120 to 180 words in total. **Bold** is fine for a name or two. No headers, no tables, no links.
7. No em dashes or en dashes anywhere. Use commas, colons or full stops.
8. Output only the take: no preamble, no sign-off, no notes about the rules.

The voice Tristan likes, as phrases rather than facts: "and I rate it 🔴⚪", "gutting", "Right call.", "Where it could bite us:", "I'm calling 2-0." """


def prompt(event, facts):
    ours, theirs, prev = facts["ours"], facts["theirs"], facts["prev"]
    opp = event.get("opponent") or (theirs or {}).get("team", "the opposition")
    where = "at home" if event.get("home") == TEAM else "away"
    lines = [VOICE, "", "FACTS",
             f"Match: {event['home']} v {event['away']}, {event.get('comp', '')}, "
             f"{event.get('venue', '')}, {event['kickoff'][:10]}. Arsenal are {where}.",
             "Positions are ESPN's: G keeper, D defender, M midfielder, F forward, RB/LB full-backs, "
             "CD-R/CD-L centre-backs, CM/DM/AM central, LM/RM/AM-L/AM-R/LF/RF wide or that side.",
             "",
             f"Arsenal today ({ours['formation']}): {_xi_line(ours)}",
             "Arsenal bench: " + ", ".join(p["name"] for p in ours["bench"])]
    if prev:
        po, ch = facts["prev_ours"], facts["changes"]
        lines += ["",
                  f"Our last competitive match: {prev['home']} {prev['home_goals']}-{prev['away_goals']} "
                  f"{prev['away']}, {prev.get('comp', '')}, {prev['kickoff'][:10]}.",
                  f"Arsenal that day ({po['formation']}): {_xi_line(po)}",
                  "Changes worked out from the two XIs: in " + (", ".join(p["name"] for p in ch["in"]) or "none")
                  + "; out " + (", ".join(f"{p['name']} ({why} today)" for p, why in ch["out"]) or "none") + "."]
    else:
        lines += ["", "Our last match's XI is not available, so do not talk about changes."]
    if theirs and theirs["published"]:
        lines += ["", f"{opp} today ({theirs['formation']}): {_xi_line(theirs)}",
                  f"{opp} bench: " + ", ".join(p["name"] for p in theirs["bench"])]
    lines += ["", f"{opp}'s last {FORM_GAMES} competitive results, oldest first:"]
    lines += [f"- {f}" for f in facts["form"]] or ["- not available"]
    lines += ["", f"Tracker news from the last {NEWS_HOURS} hours, newest first. Blogs and rumour mills "
                  "are mixed in with the BBC and the Guardian, so weigh the source:"]
    lines += [f"- {n}" for n in facts["news"]] or ["- none"]
    lines += ["", RULES.format(opp=opp)]
    return "\n".join(lines)


def clean(text):
    """The take as Telegram HTML: escaped, its **bold** turned into <b>, any
    stray ** dropped; and no em dashes, whatever the model does."""
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"<b>\1</b>", html.escape(text, quote=False))
    text = re.sub(r"[ \t]*\u2014[ \t]*", ", ", text.replace("**", ""))
    return re.sub(r"[ \t]+\u2013[ \t]+", ", ", text).strip()


def ask_claude(text, timeout=CLAUDE_TIMEOUT):
    """The take, or None when Claude errors, comes back empty or overruns.

    Built for launchd: absolute binary, USER set (the keychain lookup misses
    without it), prompt on stdin, no tools, no MCP, and no user settings or
    CLAUDE.md, so Tristan's hooks and memory cannot leak facts into the take.
    Its own session, so a timeout kills Claude's whole process tree."""
    user = pwd.getpwuid(os.getuid()).pw_name
    env = {"HOME": os.path.expanduser("~"), "USER": user, "LOGNAME": user,
           "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
           "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}
    cmd = [config.CLAUDE_BIN, "-p", "--model", "opus", "--output-format", "json",
           "--setting-sources=project", "--tools=", "--strict-mcp-config",
           "--no-session-persistence"]
    try:
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                    env=env, cwd=cwd, start_new_session=True)
            try:
                out, _ = proc.communicate(text, timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                return None
        reply = json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if proc.returncode or reply.get("is_error"):
        return None
    take = clean(reply.get("result") or "")
    return take if 0 < len(take) <= MAX_TAKE_CHARS else None


def message(event, data, plain, now=None):
    """The one lineup message: the code-built XI block, then the take, or the
    plain changes when Claude lets us down, or just the XI if even that is
    missing."""
    now = now or datetime.now(timezone.utc)
    # gathering may cache our last match; commit before the slow Claude call so
    # this process never holds the database while the alerter needs it
    with db.get_conn() as conn:
        facts = gather(conn, event, data, now)
    take = ask_claude(prompt(event, facts))
    if take:
        return f"{plain}\n\n{take}"
    if facts["changes"]:
        return f"{plain}\n\n{html.escape(changes_text(facts['changes'], facts['prev']), quote=False)}"
    return plain


if __name__ == "__main__":
    # Preview only: builds the message for a match and prints it. Never sends.
    import live_alerts

    event_id = sys.argv[1]
    at = datetime.fromisoformat(sys.argv[sys.argv.index("--at") + 1]) if "--at" in sys.argv else None
    with db.get_conn() as conn:
        event = matchcentre.find_event(fixtures.get_cached(conn) or {}, event_id)
    data = matchcentre._get(matchcentre.SUMMARY.format(league=event.get("league") or "eng.1"),
                            {"event": event["id"]})
    plain = dict(live_alerts.build_alerts(event, data, None, set()))["lineup"]
    print(message(event, data, plain, at))
