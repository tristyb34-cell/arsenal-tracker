"""Match centre: lineups, live timeline and opponent context for one fixture.

ESPN's summary endpoint carries everything Tristan asked for. Starting XIs
appear roughly an hour before kickoff (`rosters[].roster[].starter` plus a
`formation` string), and `keyEvents` carries goals, cards and subs as readable
sentences once the match is under way.

Cached in kv_cache under `match:<event_id>`. The TTL follows the match state:
a finished match never changes, a live one changes every minute.
"""

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

# Tristan's words: he does not care about the opponent unless they are one of
# these. Everyone else gets a crest and nothing more.
BIG_CLUBS = {
    "Manchester City", "Liverpool", "Manchester United", "Chelsea",
    "Tottenham Hotspur", "Newcastle United",
    "Real Madrid", "Barcelona", "Bayern Munich", "Paris Saint-Germain",
    "Inter Milan", "Atletico Madrid", "AC Milan", "Juventus", "Borussia Dortmund",
}

GOAL_TYPES = {"Goal", "Own Goal", "Penalty - Scored"}
BIG_EVENT_TYPES = GOAL_TYPES | {"Red Card", "Yellow Red Card"}


def _get(url, params=None):
    r = requests.get(url, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _ttl(event):
    if event.get("live"):
        return TTL_LIVE
    if event.get("finished"):
        return TTL_FINISHED
    try:
        mins = (datetime.fromisoformat(event["kickoff"])
                - datetime.now(timezone.utc)).total_seconds() / 60
    except (KeyError, ValueError):
        return TTL_UPCOMING
    return TTL_PREMATCH if mins <= 180 else TTL_UPCOMING


def build(event):
    """Fetch and shape the match centre payload for one fixture."""
    data = _get(SUMMARY.format(league=event.get("league", "eng.1")),
                {"event": event["id"]})
    return {
        "lineups": _lineups(data),
        "timeline": _timeline(data),
        "info": _info(data),
        "opponent": _opponent(event, data),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def _lineups(data):
    out = []
    for r in data.get("rosters") or []:
        players = [_player(p) for p in r.get("roster") or []]
        starters = [p for p in players if p["starter"]]
        starters.sort(key=lambda p: p["place"])
        out.append({
            "team": (r.get("team") or {}).get("displayName", ""),
            "logo": (r.get("team") or {}).get("logo", ""),
            "colour": (r.get("team") or {}).get("color", "") or "",
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
    out = []
    for e in data.get("keyEvents") or []:
        kind = (e.get("type") or {}).get("text", "")
        text = (e.get("text") or "").strip()
        if not text or kind in ("Start Delay", "End Delay"):
            continue
        scoring = bool(e.get("scoringPlay")) or kind in GOAL_TYPES
        out.append({
            "minute": (e.get("clock") or {}).get("displayValue", ""),
            "type": kind,
            "text": text,
            "scoring": scoring,
            "ours": scoring and _scored_by_arsenal(text),
            "big": kind in BIG_EVENT_TYPES,
        })
    return out


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
    return {
        "venue": venue.get("fullName", ""),
        "city": (venue.get("address") or {}).get("city", ""),
        "attendance": g.get("attendance"),
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
        st = comp["status"]["type"]
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
    }


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def get(conn, event, force=False):
    """Cached match centre payload. Returns None if ESPN is unreachable."""
    key = f"match:{event['id']}"
    row = db.kv_get(conn, key)
    if row and row["value"] and not force:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row["updated_at"])
            if age < _ttl(event):
                return json.loads(row["value"])
        except (ValueError, json.JSONDecodeError):
            pass
    try:
        payload = build(event)
    except Exception:
        if row and row["value"]:
            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                return None
        return None
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
