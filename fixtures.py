"""Arsenal fixtures, results, form, and the Premier League table via ESPN's
free public API (no key). Pattern borrowed from the betting app's espn source.

Cached into kv_cache so the dashboard reads instantly; refreshed by scrape.py.
Degrades gracefully in the off-season (no upcoming fixture -> show last result
and final table).
"""

import json
from datetime import datetime, timedelta, timezone

import requests

import config
import db

EPL = "eng.1"
SCOREBOARD = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{EPL}/scoreboard"
STANDINGS = f"https://site.api.espn.com/apis/v2/sports/soccer/{EPL}/standings"
TEAM = "Arsenal"
FINISHED = {"STATUS_FULL_TIME", "STATUS_FINAL_AET", "STATUS_FINAL_PEN", "STATUS_FT"}


def _get(url, params=None):
    r = requests.get(url, params=params or {},
                     headers={"User-Agent": config.USER_AGENT}, timeout=15)
    r.raise_for_status()
    return r.json()


def _ymd(dt):
    return dt.strftime("%Y%m%d")


def _arsenal_events(days_back=50, days_ahead=160, slice_days=24):
    """Collect Arsenal fixtures across the window. ESPN caps events per request
    for wide date ranges, so we fetch in <=24-day slices and merge."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)
    end = now + timedelta(days=days_ahead)

    seen = {}
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=slice_days), end)
        try:
            data = _get(SCOREBOARD, {"dates": f"{_ymd(cursor)}-{_ymd(chunk_end)}"})
        except Exception:
            cursor = chunk_end + timedelta(days=1)
            continue
        for e in data.get("events", []):
            if TEAM not in e.get("name", ""):
                continue
            try:
                comp = e["competitions"][0]
                cs = comp["competitors"]
                home = next(t for t in cs if t["homeAway"] == "home")
                away = next(t for t in cs if t["homeAway"] == "away")
                status = comp["status"]["type"]["name"]
                ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                seen[e.get("id", ko.isoformat())] = {
                    "kickoff": ko.isoformat(),
                    "home": home["team"]["displayName"],
                    "away": away["team"]["displayName"],
                    "home_short": home["team"].get("abbreviation", ""),
                    "away_short": away["team"].get("abbreviation", ""),
                    "home_goals": _maybe_int(home.get("score")),
                    "away_goals": _maybe_int(away.get("score")),
                    "finished": status in FINISHED,
                }
            except (KeyError, StopIteration, ValueError):
                continue
        cursor = chunk_end + timedelta(days=1)

    out = list(seen.values())
    out.sort(key=lambda x: x["kickoff"])
    return out


def _maybe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _result_for_arsenal(ev):
    """Return 'W' / 'D' / 'L' for a finished Arsenal fixture."""
    if not ev["finished"] or ev["home_goals"] is None:
        return None
    ars_home = ev["home"] == TEAM
    gf = ev["home_goals"] if ars_home else ev["away_goals"]
    ga = ev["away_goals"] if ars_home else ev["home_goals"]
    return "W" if gf > ga else ("D" if gf == ga else "L")


def _standings_rows():
    data = _get(STANDINGS)
    entries = _find_entries(data)
    table = []
    for e in entries or []:
        stats = {s["name"]: s.get("displayValue") for s in e.get("stats", [])}
        table.append({
            "rank": _maybe_int(stats.get("rank")),
            "team": e["team"]["displayName"],
            "team_short": e["team"].get("abbreviation", ""),
            "played": stats.get("gamesPlayed"),
            "points": stats.get("points"),
            "gd": stats.get("pointDifferential") or stats.get("goalDifference"),
        })
    table.sort(key=lambda r: r["rank"] or 99)
    return table


def _find_entries(o):
    if isinstance(o, dict):
        s = o.get("standings")
        if isinstance(s, dict) and "entries" in s:
            return s["entries"]
        for v in o.values():
            r = _find_entries(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_entries(v)
            if r:
                return r
    return None


def build_snapshot():
    """Fetch everything and assemble the dashboard's football snapshot."""
    events = _arsenal_events()
    now = datetime.now(timezone.utc)

    past = [e for e in events if e["finished"]]
    upcoming = [e for e in events
                if not e["finished"] and datetime.fromisoformat(e["kickoff"]) >= now]

    last = past[-1] if past else None
    nxt = upcoming[0] if upcoming else None
    form = [r for r in (_result_for_arsenal(e) for e in past[-5:]) if r]

    table = _standings_rows()
    arsenal_row = next((r for r in table if r["team"] == TEAM), None)

    return {
        "last_result": last,
        "next_match": nxt,
        "form": form,
        "table": table,
        "arsenal_row": arsenal_row,
        "is_matchday": _is_matchday(nxt, now),
    }


def _is_matchday(nxt, now):
    if not nxt:
        return False
    ko = datetime.fromisoformat(nxt["kickoff"])
    return ko.date() == now.date()


def refresh(conn=None):
    """Build the snapshot and cache it. Safe to call every scrape."""
    own = conn is None
    if own:
        ctx = db.get_conn()
        conn = ctx.__enter__()
    try:
        snap = build_snapshot()
        db.kv_set(conn, "football", json.dumps(snap),
                  datetime.now(timezone.utc).isoformat())
        return snap
    except Exception as e:
        return {"error": str(e)}
    finally:
        if own:
            ctx.__exit__(None, None, None)


def get_cached(conn):
    row = db.kv_get(conn, "football")
    if not row or not row["value"]:
        return None
    try:
        snap = json.loads(row["value"])
        snap["_updated_at"] = row["updated_at"]
        return snap
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    db.init_db()
    snap = refresh()
    print(json.dumps({k: v for k, v in snap.items() if k != "table"}, indent=2)[:1200])
    print("table rows:", len(snap.get("table", [])))
