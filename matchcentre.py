"""Match centre: lineups, live timeline and opponent context for one fixture.

ESPN's summary endpoint carries everything Tristan asked for. Starting XIs
appear roughly an hour before kickoff (`rosters[].roster[].starter` plus a
`formation` string), and `keyEvents` carries goals, cards and subs as readable
sentences once the match is under way.

Cached in kv_cache under `match:<event_id>`. The TTL follows the match state:
a finished match never changes, a live one changes every minute.
"""

import colorsys
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

import db

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary"
COMBINER = "https://a.espncdn.com/combiner/i?img={path}&w=120&h=120"
TEAM = "Arsenal"

# TTL by state. Pre-match is polled often enough to catch the lineup drop.
TTL_LIVE = timedelta(seconds=45)
TTL_PREMATCH = timedelta(minutes=5)
TTL_UPCOMING = timedelta(hours=6)
TTL_FINISHED = timedelta(days=30)

# Bump when the payload shape changes, so cached payloads built by older code
# (no scorers, no stats) are rebuilt instead of served for their 30-day TTL.
SCHEMA = 3

# Tristan's words: he does not care about the opponent unless they are one of
# these. Everyone else gets a crest and nothing more.
BIG_CLUBS = {
    "Manchester City", "Liverpool", "Manchester United", "Chelsea",
    "Tottenham Hotspur", "Newcastle United",
    "Real Madrid", "Barcelona", "Bayern Munich", "Paris Saint-Germain",
    "Inter Milan", "Atletico Madrid", "AC Milan", "Juventus", "Borussia Dortmund",
}

GOAL_TYPES = {"Goal", "Own Goal", "Penalty - Scored"}
RED_TYPES = {"Red Card", "Yellow Red Card", "Second Yellow Card"}

# keyEvents type text -> the handful of kinds the timeline draws. ESPN varies
# the goal text ("Goal - Header", "Goal - Free-kick"), so goals match on prefix.
KINDS = {
    "Penalty - Scored": "pen", "Own Goal": "og",
    "Penalty - Missed": "pen_miss", "Penalty - Saved": "pen_miss",
    "Yellow Card": "yellow", "Red Card": "red",
    "Yellow Red Card": "red", "Second Yellow Card": "red",
    "Substitution": "sub", "Kickoff": "ko", "Halftime": "ht",
    "End Regular Time": "ft", "End Extra Time": "ft",
}
SKIP_TYPES = {"Start Delay", "End Delay", "Start 2nd Half"}

# team stats worth a bar, in reading order. Only drawn when ESPN sends both
# sides (it does for every finished 2026-27 match checked on 2026-10-02).
STATS = [
    ("possessionPct", "Possession"), ("totalShots", "Shots"),
    ("shotsOnTarget", "Shots on target"), ("wonCorners", "Corners"),
    ("foulsCommitted", "Fouls"), ("offsides", "Offsides"),
    ("yellowCards", "Yellow cards"), ("redCards", "Red cards"),
    ("saves", "Saves"),
]


def _get(url, params=None):
    r = requests.get(url, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _ttl(event):
    if event.get("finished"):
        return TTL_FINISHED
    if event.get("live"):
        return TTL_LIVE
    try:
        mins = (datetime.fromisoformat(event["kickoff"])
                - datetime.now(timezone.utc)).total_seconds() / 60
    except (KeyError, ValueError):
        return TTL_UPCOMING
    if -180 <= mins <= 0:
        # kicked off, but the fixtures cache (rebuilt every 90 minutes) may not
        # know yet. Treat it as live rather than polling every five minutes.
        return TTL_LIVE
    return TTL_PREMATCH if mins <= 180 else TTL_UPCOMING


def build(event):
    """Fetch and shape the match centre payload for one fixture."""
    data = _get(SUMMARY.format(league=event.get("league", "eng.1")),
                {"event": event["id"]})
    return shape(event, data)


def shape(event, data):
    timeline = _timeline(data)
    state = live_state(data)
    return {
        "status": state,
        "scorers": scorers(timeline, _short_names(data)),
        "timeline": with_markers(timeline, state),
        "stats": _stats(data),
        "lineups": _lineups(data),
        "info": _info(data),
        "opponent": _opponent(event, data),
        "schema": SCHEMA,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def _lineups(data):
    marks = _player_marks(data)
    out = []
    for r in data.get("rosters") or []:
        players = [_player(p) for p in r.get("roster") or []]
        for p in players:
            p["marks"] = marks.get(p["id"], [])
        starters = [p for p in players if p["starter"]]
        starters.sort(key=lambda p: p["place"])
        team = r.get("team") or {}
        kit, ink = kit_colours(team.get("color"), team.get("alternateColor"),
                               team.get("displayName") == TEAM)
        out.append({
            "team": team.get("displayName", ""),
            "logo": team.get("logo", ""),
            "colour": team.get("color", "") or "",
            "kit": kit,
            "ink": ink,
            "home_away": r.get("homeAway", ""),
            "formation": r.get("formation") or "",
            "rows": _shape(starters, r.get("formation") or ""),
            "bench": [p for p in players if not p["starter"]],
            "published": bool(starters),
        })
    return out


def _player(p):
    a = p.get("athlete") or {}
    return {
        "id": str(a.get("id") or ""),
        "name": a.get("displayName") or a.get("fullName") or "",
        "short": a.get("shortName") or "",
        "jersey": p.get("jersey") or a.get("jersey") or "",
        "pos": (p.get("position") or {}).get("abbreviation", ""),
        "starter": bool(p.get("starter")),
        "place": int(p.get("formationPlace") or 99),
        "subbed_off": _subbed(p.get("subbedOut")),
        "subbed_on": _subbed(p.get("subbedIn")),
        "photo": _headshot(a),
    }


def _band(pos):
    """Reduce an ESPN position code to its pitch band: G, D, M or F.

    The codes are not always the bare letter. Arsenal v Napoli returned
    "G"/"D"/"M"/"F", but Arsenal v Chelsea returned "CD-L", "CM-R", "LM" and
    "CF-R" for the same idea, and Arsenal v Coventry used "LB"/"RB" for the
    full-backs. Matching on the first letter therefore placed nobody, the "did
    every starter get a row" guard tripped, and those XIs rendered as one flat
    line of eleven. Dropping the side suffix and reading the last letter of the
    base handles all of them: CD-L, LM and RB are a defender, a midfielder and
    a defender. Codes seen live across the Napoli, Chelsea, Villa and Coventry
    fixtures: G, D, CD, CD-L, CD-R, LB, RB, M, DM, AM, AM-L, AM-R, LM, RM,
    CM-L, CM-R, F, CF-L, CF-R. Anything else returns "" and still trips the
    guard, which is the intended safety net rather than a silent mis-placement.
    """
    base = (pos or "").upper().split("-")[0].strip()
    if not base or base == "SUB":
        # "SUB" is a status, not a position, and it would otherwise be read as
        # a back and land a substitute in the defensive line
        return ""
    # B is a full-back, which belongs in the defensive line
    return {"B": "D"}.get(base[-1], base[-1]) if base[-1] in "GDMFB" else ""


def _subbed(v):
    """ESPN changes this field's shape when a match ends: `{"didSub": true}`
    while the game is upcoming or live, then a bare `true` once it is finished.
    Only the dict form was handled, so `.get` raised on every completed match,
    `get()` swallowed it and the page fell back to "Couldn't reach ESPN".
    """
    return bool(v.get("didSub") if isinstance(v, dict) else v)


def _headshot(a):
    """Photo URL for one athlete, or "" when ESPN has none.

    Only the declared `athlete.headshot.href` is trusted. Building the URL from
    the athlete id instead is tempting and wrong: checked live on 2026-09-09,
    `a.espncdn.com/i/headshots/soccer/players/full/<id>.png` 404d for 19 of 20
    real ids from this very fixture, so a generated URL would have put a broken
    image on nearly every shirt. ESPN's soccer coverage is genuinely sparse
    (3 of 42 athletes in the Arsenal v Napoli payload, none of them starters),
    so an empty string is the normal case, not an error.

    The declared href points at the ~600px original. Swapping it onto ESPN's
    combiner returns the same picture as a 120px square cut-out, roughly a
    sixteenth of the bytes and already framed for a round avatar.

    Only PNGs are returned. The shirt disc keeps its kit colour behind the
    photo and relies on the cut-out being transparent, so an opaque JPEG would
    render as a square-ish tile with no team colour left. Every headshot ESPN
    has served is a PNG; anything else is dropped rather than displayed wrong.
    """
    href = ((a.get("headshot") or {}).get("href") or "").strip()
    if not href:
        return ""
    path = urlsplit(href).path
    return COMBINER.format(path=path) if path.endswith(".png") else ""


def _shape(starters, formation):
    """Lay the XI out as pitch rows, keeper first.

    ESPN's `formationPlace` is a slot id, not a back-to-front sequence: in the
    Napoli match Declan Rice sat at place 4 and slicing the "4-2-3-1" bands in
    place order dropped him into the back four, with Lobotka in Napoli's. So the
    rows come from the players' actual positions (G, D, M, F) instead, which is
    right on every match. The formation string is still shown as a label; it is
    just no longer trusted to reconstruct the shape."""
    def line(code):
        return sorted([p for p in starters if _band(p["pos"]) == code],
                      key=lambda p: p["place"])

    rows = [line("G"), line("D"), line("M"), line("F")]
    rows = [r for r in rows if r]
    placed = sum(len(r) for r in rows)
    if placed != len(starters):
        # an unexpected position code: fall back to one flat row rather than
        # silently dropping a player off the pitch
        return [starters] if starters else []
    return rows


def _timeline(data):
    """Goals, cards and subs in match order, each tagged with its side.

    `team` on a key event is the side that BENEFITED: checked against three
    real own goals on 2026-10-02, "Own Goal by Piero Hincapie, Arsenal" carries
    team=Chelsea. So `side` is always the side whose score went up, and the
    player named first is the one who put it in the net, either end."""
    sides = _sides(data)
    short = _short_names(data)
    goals = {"home": 0, "away": 0}
    out = []
    for e in data.get("keyEvents") or []:
        kind_text = (e.get("type") or {}).get("text", "")
        text = (e.get("text") or "").strip()
        if not text or kind_text in SKIP_TYPES or e.get("shootout"):
            # shootout kicks are not goals; the fixture note carries the result
            continue
        scoring = bool(e.get("scoringPlay")) or kind_text in GOAL_TYPES
        kind = KINDS.get(kind_text) or ("goal" if scoring or kind_text.startswith("Goal") else "other")
        team = (e.get("team") or {})
        side = sides.get(str(team.get("id") or ""), "")
        names = [((x.get("athlete") or {}).get("displayName") or "")
                 for x in e.get("participants") or []]
        row = {
            "minute": (e.get("clock") or {}).get("displayValue", ""),
            "type": kind_text,
            "text": text,
            "scoring": scoring,
            "ours": scoring and (team.get("displayName") == TEAM
                                 if team.get("displayName") else _scored_by_arsenal(text)),
            "big": scoring or kind_text in RED_TYPES,
            "kind": kind,
            "side": side,
            "player": names[0] if names else "",
            # the assist for a goal, the player going off for a sub
            "detail": names[1] if len(names) > 1 and kind in ("goal", "sub") else "",
            # pitch-style surnames for a phone-width timeline ("De Bruyne")
            "player_short": short.get(names[0], "") if names else "",
            "detail_short": short.get(names[1], "") if len(names) > 1 else "",
            "period": (e.get("period") or {}).get("number"),
            "secs": (e.get("clock") or {}).get("value"),
        }
        if scoring and side:
            goals[side] += 1
            row["score"] = f"{goals['home']}–{goals['away']}"
        if kind in ("ht", "ft"):
            row["score"] = f"{goals['home']}–{goals['away']}"
        out.append(row)
    return out


def with_markers(timeline, state):
    """The timeline as drawn: ESPN's own period markers swapped for our own.

    ESPN sends "Halftime" and "End Regular Time" for some matches and not
    others (4 of 8 finished 2026-27 games had no half-time marker), so a
    timeline built from them looked different match to match. HT goes after
    the last first-half event once the second half exists, FT once the match
    is complete, each carrying the score at that point. Kept out of
    _timeline() itself because live_alerts keys alerts by list position."""
    events = [t for t in timeline if t["kind"] not in ("ko", "ht", "ft")]
    state = state or {}
    second_half = any((t.get("period") or 1) >= 2 for t in events) or \
        state.get("name") == "STATUS_HALFTIME" or (state.get("period") or 0) >= 2 or \
        bool(state.get("completed"))
    out, goals, ht_done = [], {"home": 0, "away": 0}, False
    for t in events:
        if second_half and not ht_done and (t.get("period") or 1) >= 2:
            out.append(_marker("ht", "HT", goals))
            ht_done = True
        out.append(t)
        if t["scoring"] and t["side"] in goals:
            goals[t["side"]] += 1
    if second_half and not ht_done:
        out.append(_marker("ht", "HT", goals))
    if state.get("completed"):
        if state.get("home_goals") is not None:
            goals = {"home": state["home_goals"], "away": state["away_goals"]}
        out.append(_marker("ft", "FT", goals))
    return out


def _marker(kind, label, goals):
    return {"minute": label, "type": label, "text": "", "scoring": False, "ours": False,
            "big": False, "kind": kind, "side": "", "player": "", "detail": "",
            "player_short": "", "detail_short": "",
            "period": None, "secs": None, "score": f"{goals['home']}–{goals['away']}"}


def _sides(data):
    """team id -> "home"/"away", from the summary header."""
    try:
        comps = data["header"]["competitions"][0]["competitors"]
    except (KeyError, IndexError, TypeError):
        return {}
    return {str(c.get("id") or (c.get("team") or {}).get("id")): c.get("homeAway", "")
            for c in comps}


def _short_names(data):
    """athlete id and display name -> pitch-style surname ("De Bruyne")."""
    out = {}
    for r in data.get("rosters") or []:
        for p in r.get("roster") or []:
            a = p.get("athlete") or {}
            short = surname(a.get("shortName") or a.get("displayName") or "")
            for key in (a.get("displayName"), str(a.get("id") or "")):
                if key:
                    out[key] = short
    return out


def surname(name):
    """"K. De Bruyne" becomes "De Bruyne", not "Bruyne". The leading initial is
    the only part worth dropping."""
    parts = (name or "").split(" ")
    if len(parts) > 1 and parts[0].endswith(".") and len(parts[0]) <= 2:
        return " ".join(parts[1:])
    return name or ""


def scorers(timeline, short=None):
    """Goal scorers per side, minutes in order, pens and own goals marked.

    An own goal is listed under the side it counted for, which is how every
    broadcaster shows it ("Hincapie 45+2' (OG)" under Chelsea)."""
    short = short or {}
    out = {"home": [], "away": []}
    for ev in timeline:
        if not ev["scoring"] or ev["side"] not in out:
            continue
        name = short.get(ev["player"]) or (ev["player"].split(" ")[-1] if ev["player"] else "Goal")
        rows = out[ev["side"]]
        row = next((r for r in rows if r["name"] == name and r["og"] == (ev["kind"] == "og")), None)
        if not row:
            row = {"name": name, "og": ev["kind"] == "og", "goals": []}
            rows.append(row)
        row["goals"].append({"minute": ev["minute"], "pen": ev["kind"] == "pen"})
    return out


def _player_marks(data):
    """athlete id -> the badges drawn on that player's disc: goals, assists,
    cards and the minute he came off or on."""
    marks = {}

    def add(pid, kind, minute):
        if pid:
            marks.setdefault(pid, []).append({"kind": kind, "minute": minute})

    for e in data.get("keyEvents") or []:
        if e.get("shootout"):
            continue
        kind_text = (e.get("type") or {}).get("text", "")
        scoring = bool(e.get("scoringPlay")) or kind_text in GOAL_TYPES
        kind = KINDS.get(kind_text) or ("goal" if scoring or kind_text.startswith("Goal") else "")
        ids = [str((x.get("athlete") or {}).get("id") or "") for x in e.get("participants") or []]
        minute = (e.get("clock") or {}).get("displayValue", "")
        if not ids:
            continue
        if kind in ("goal", "pen"):
            add(ids[0], "goal", minute)
            if len(ids) > 1 and kind == "goal":
                add(ids[1], "assist", minute)
        elif kind in ("og", "yellow", "red"):
            add(ids[0], kind, minute)
        elif kind == "sub":
            add(ids[0], "on", minute)
            if len(ids) > 1:
                add(ids[1], "off", minute)
    return marks


def _stats(data):
    sides = _sides(data)
    by_side = {}
    for t in (data.get("boxscore") or {}).get("teams") or []:
        side = sides.get(str((t.get("team") or {}).get("id") or ""))
        if side:
            by_side[side] = {x.get("name"): x.get("displayValue") for x in t.get("statistics") or []}
    if set(by_side) != {"home", "away"}:
        return []
    out = []
    for key, label in STATS:
        h, a = _num(by_side["home"].get(key)), _num(by_side["away"].get(key))
        if h is None or a is None:
            continue
        out.append({"key": key, "label": label, "home": h, "away": a,
                    "pct": key == "possessionPct"})
    # a payload of all zeros is a match that has not started, not a stat line
    return out if any(s["home"] or s["away"] for s in out) else []


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 1)


def kit_colours(colour, alternate, is_arsenal):
    """Shirt disc fill and number colour for one side.

    Arsenal always wear the brand red (set in CSS). An opponent whose primary
    colour is also red switches to its alternate so the two XIs never share a
    colour. The number colour is whichever of white or near-black reads better
    on the fill, so a white or sky-blue kit no longer carries white numbers."""
    if is_arsenal:
        return "", "light"
    for c in (colour, alternate):
        rgb = _rgb(c)
        if rgb and not _reddish(rgb):
            return "#" + c.lower(), _ink(rgb)
    return "#7c889d", "dark"


def _rgb(hexstr):
    h = (hexstr or "").strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None


def _reddish(rgb):
    hue, light, sat = colorsys.rgb_to_hls(*rgb)
    deg = hue * 360
    return (deg >= 345 or deg <= 15) and sat > 0.45 and 0.2 < light < 0.75


def _ink(rgb):
    def lum(c):
        lin = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    bg = lum(rgb)
    on_white = 1.05 / (bg + 0.05)
    on_dark = (bg + 0.05) / (lum((10 / 255, 14 / 255, 22 / 255)) + 0.05)
    return "light" if on_white >= on_dark else "dark"


def _scored_by_arsenal(text):
    """ESPN writes 'Goal! Napoli 1, Arsenal 0. Rasmus Hojlund (Napoli) ...', so
    the club in the first bracket is the one that scored."""
    start = text.find("(")
    end = text.find(")", start + 1)
    return start > 0 and end > start and text[start + 1:end].strip() == TEAM


def _info(data):
    g = data.get("gameInfo") or {}
    venue = g.get("venue") or {}
    casts = data.get("broadcasts") or []
    names = []
    for b in casts:
        names += [m.get("shortName") or m.get("name") for m in (b.get("media") and [b["media"]] or [])]
    referee = next((o.get("displayName") for o in g.get("officials") or []
                    if ((o.get("position") or {}).get("name") or "") == "Referee"), "")
    return {
        "venue": venue.get("fullName", ""),
        "city": (venue.get("address") or {}).get("city", ""),
        "attendance": g.get("attendance"),
        "referee": referee or "",
        "broadcast": ", ".join(n for n in names if n),
    }


def _opponent(event, data):
    """Only the clubs Tristan actually cares about get a profile block."""
    name = event.get("opponent", "")
    if name not in BIG_CLUBS:
        return None
    form = None
    for block in data.get("lastFiveGames") or []:
        if (block.get("team") or {}).get("displayName") == name:
            form = [_mini(g) for g in (block.get("events") or [])][:5]
    standing = None
    for s in ((data.get("standings") or {}).get("groups") or []):
        for entry in ((s.get("standings") or {}).get("entries") or []):
            t = entry.get("team")
            # the summary endpoint writes this entry's team as a plain display
            # name, while other ESPN standings payloads use a full object
            if (t if isinstance(t, str) else (t or {}).get("displayName", "")) == name:
                stats = {x["name"]: x.get("displayValue") for x in entry.get("stats", [])}
                standing = {"rank": stats.get("rank"), "points": stats.get("points"),
                            "played": stats.get("gamesPlayed")}
    return {"name": name, "form": form, "standing": standing} if (form or standing) else None


def _mini(g):
    return {
        "opponent": g.get("opponent", {}).get("displayName", ""),
        "score": g.get("score", ""),
        "result": (g.get("gameResult") or "").upper()[:1],
        "date": g.get("gameDate", "")[:10],
    }


def live_state(data):
    """Status and score straight off the summary header, so the alert loop does
    not need a second scoreboard call."""
    try:
        comp = data["header"]["competitions"][0]
        status = comp["status"]
        st = status["type"]
        goals = {c["homeAway"]: _int(c.get("score")) for c in comp["competitors"]}
        teams = {c["homeAway"]: (c.get("team") or {}).get("displayName", "")
                 for c in comp["competitors"]}
    except (KeyError, IndexError, TypeError):
        return None
    return {
        "state": st.get("state", ""),
        "name": st.get("name", ""),
        "detail": st.get("shortDetail", ""),
        "completed": bool(st.get("completed")),
        "home": teams.get("home", ""), "away": teams.get("away", ""),
        "home_goals": goals.get("home"), "away_goals": goals.get("away"),
        # seconds played, so a phone can keep the minute ticking between polls
        "clock": status.get("clock"),
        "display_clock": status.get("displayClock", ""),
        "period": status.get("period"),
        "clock_at": datetime.now(timezone.utc).isoformat(),
    }


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _fresh(cached, row, event):
    if cached.get("schema") != SCHEMA:
        return False
    if event.get("finished") and not (cached.get("status") or {}).get("completed"):
        # captured while the game was still on: the 30-day finished TTL would
        # otherwise freeze an 88th-minute timeline as the final record
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["updated_at"])
    except (TypeError, ValueError):
        return False
    return age < _ttl(event)


def get(conn, event, force=False):
    """Cached match centre payload. Returns None if ESPN is unreachable."""
    key = f"match:{event['id']}"
    row = db.kv_get(conn, key)
    cached = None
    if row and row["value"]:
        try:
            cached = json.loads(row["value"])
        except json.JSONDecodeError:
            cached = None
    if cached and not force and _fresh(cached, row, event):
        return cached
    try:
        payload = build(event)
    except Exception:
        return cached
    db.kv_set(conn, key, json.dumps(payload),
              datetime.now(timezone.utc).isoformat())
    return payload


def find_event(snap, event_id):
    for bucket in ("fixtures", "results"):
        for e in snap.get(bucket) or []:
            if str(e["id"]) == str(event_id):
                return e
    for k in ("live_match", "next_match", "last_result"):
        e = snap.get(k)
        if e and str(e["id"]) == str(event_id):
            return e
    return None


def arsenal_side(lineups):
    return next((x for x in lineups if x["team"] == TEAM), None)


def opponent_side(lineups):
    return next((x for x in lineups if x["team"] != TEAM), None)
