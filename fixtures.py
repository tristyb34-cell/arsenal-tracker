"""Arsenal fixtures, results, form, and the Premier League table via ESPN's
free public API (no key). Pattern borrowed from the betting app's espn source.

Covers every competition Arsenal play in, not just the league: Premier League,
Champions League, FA Cup, Carabao Cup, Community Shield and the UEFA Super Cup.

Cached into kv_cache so the dashboard reads instantly; refreshed by scrape.py.
Degrades gracefully in the off-season (no upcoming fixture -> show last result
and final table).
"""

import json
from datetime import datetime, timedelta, timezone

import requests

import db

EPL = "eng.1"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
STANDINGS = f"https://site.api.espn.com/apis/v2/sports/soccer/{EPL}/standings"
TEAM = "Arsenal"
PAGE_CAP = 100  # ESPN truncates a scoreboard response here, without saying so
FINISHED = {"STATUS_FULL_TIME", "STATUS_FINAL_AET", "STATUS_FINAL_PEN", "STATUS_FT"}
LIVE = {"STATUS_IN_PROGRESS", "STATUS_FIRST_HALF", "STATUS_SECOND_HALF",
        "STATUS_HALFTIME", "STATUS_EXTRA_TIME", "STATUS_SHOOTOUT"}

# ESPN league slug, display name, short badge, css slug, how many days to fetch
# per request. Dense competitions must use narrow slices: ESPN caps a single
# scoreboard response at 100 events, and anything past that is silently dropped.
COMPS = [
    ("eng.1", "Premier League", "PL", "pl", 45),
    ("uefa.champions", "Champions League", "UCL", "ucl", 45),
    ("eng.fa", "FA Cup", "FA", "fa", 60),
    ("eng.league_cup", "Carabao Cup", "EFL", "efl", 60),
    ("eng.charity", "Community Shield", "CS", "cs", 90),
    ("uefa.super_cup", "Super Cup", "USC", "usc", 90),
]
COMP_ORDER = {c[1]: i for i, c in enumerate(COMPS)}


def _get(url, params=None):
    # ESPN 403s on browser-spoofed UAs (started 2026-08-04). Plain requests UA works.
    r = requests.get(url, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _ymd(dt):
    return dt.strftime("%Y%m%d")


def _season_start(now):
    """European seasons run July to June. Anything before 1 July belongs to the
    previous campaign and must not count towards this season's record or form."""
    year = now.year if now.month >= 7 else now.year - 1
    return datetime(year, 7, 1, tzinfo=timezone.utc)


def _arsenal_events(days_ahead=330):
    """Collect Arsenal fixtures across every competition, this season only."""
    now = datetime.now(timezone.utc)
    start = _season_start(now)
    end = min(now + timedelta(days=days_ahead),
              _season_start(now) + timedelta(days=365))

    seen = {}
    for league, comp_name, comp_code, comp_slug, slice_days in COMPS:
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=slice_days), end)
            _collect(league, comp_name, comp_code, comp_slug, cursor, chunk_end, seen)
            cursor = chunk_end + timedelta(days=1)

    out = list(seen.values())
    out.sort(key=lambda x: x["kickoff"])
    return out


def _collect(league, comp_name, comp_code, comp_slug, start, end, seen):
    """Fetch one date range, and split it if ESPN hit its response cap.

    ESPN silently truncates a scoreboard response at PAGE_CAP events. A busy cup
    round is enough to blow past that and quietly drop the Arsenal tie, which is
    how the Carabao third round went missing. If a window comes back full, halve
    it and go again rather than trusting a suspiciously round number."""
    try:
        data = _get(SCOREBOARD.format(league=league),
                    {"dates": f"{_ymd(start)}-{_ymd(end)}"})
    except Exception:
        return
    events = data.get("events", [])
    if len(events) >= PAGE_CAP and (end - start).days > 1:
        mid = start + (end - start) / 2
        _collect(league, comp_name, comp_code, comp_slug, start, mid, seen)
        _collect(league, comp_name, comp_code, comp_slug, mid + timedelta(days=1), end, seen)
        return
    for e in events:
        if TEAM not in e.get("name", ""):
            continue
        ev = _parse_event(e, comp_name, comp_code, comp_slug)
        if ev:
            ev["league"] = league
            seen[ev["id"]] = ev


def _parse_event(e, comp_name, comp_code, comp_slug):
    try:
        comp = e["competitions"][0]
        cs = comp["competitors"]
        home = next(t for t in cs if t["homeAway"] == "home")
        away = next(t for t in cs if t["homeAway"] == "away")
        status = comp["status"]["type"]["name"]
        ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
    except (KeyError, IndexError, StopIteration, ValueError):
        return None
    return {
        "id": e.get("id", ko.isoformat()),
        "url": _event_url(e),
        "kickoff": ko.isoformat(),
        "comp": comp_name,
        "comp_code": comp_code,
        "comp_slug": comp_slug,
        "round": (comp.get("notes") or [{}])[0].get("headline", "") if comp.get("notes") else "",
        "venue": (comp.get("venue") or {}).get("fullName", ""),
        "home": home["team"]["displayName"],
        "away": away["team"]["displayName"],
        "home_short": home["team"].get("abbreviation", ""),
        "away_short": away["team"].get("abbreviation", ""),
        "home_logo": home["team"].get("logo", ""),
        "away_logo": away["team"].get("logo", ""),
        "home_goals": _maybe_int(home.get("score")),
        "away_goals": _maybe_int(away.get("score")),
        "finished": status in FINISHED,
        "live": status in LIVE,
        "status": comp["status"]["type"].get("shortDetail", ""),
    }


def _event_url(e):
    """ESPN's own match page, so a fixture row has somewhere to go."""
    for link in e.get("links", []):
        href = link.get("href", "")
        if href.startswith("http") and "desktop" in link.get("rel", []):
            return href
    return ""


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


def _decorate(ev):
    """Add the Arsenal-eye-view fields the templates render."""
    ars_home = ev["home"] == TEAM
    ev["opponent"] = ev["away"] if ars_home else ev["home"]
    ev["opponent_short"] = (ev["away_short"] if ars_home else ev["home_short"]) or ev["opponent"][:3].upper()
    ev["opponent_logo"] = ev["away_logo"] if ars_home else ev["home_logo"]
    ev["home_away"] = "H" if ars_home else "A"
    ev["result"] = _result_for_arsenal(ev)
    if ev["home_goals"] is not None and ev["away_goals"] is not None:
        ev["score"] = (f"{ev['home_goals']}–{ev['away_goals']}" if ars_home
                       else f"{ev['away_goals']}–{ev['home_goals']}")
    else:
        ev["score"] = ""
    return ev


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
    events = [_decorate(e) for e in _arsenal_events()]
    now = datetime.now(timezone.utc)

    past = [e for e in events if e["finished"]]
    live = [e for e in events if e["live"]]
    upcoming = [e for e in events
                if not e["finished"] and not e["live"]
                and datetime.fromisoformat(e["kickoff"]) >= now]

    last = past[-1] if past else None
    nxt = upcoming[0] if upcoming else None
    form = [r for r in (_result_for_arsenal(e) for e in past[-5:]) if r]

    table = _standings_rows()
    arsenal_row = next((r for r in table if r["team"] == TEAM), None)

    return {
        "last_result": last,
        "next_match": nxt,
        "live_match": live[0] if live else None,
        "form": form,
        "fixtures": upcoming,
        "results": list(reversed(past)),
        "comps": _comp_summary(past, upcoming),
        "table": table,
        "arsenal_row": arsenal_row,
        "is_matchday": _is_matchday(nxt, live, now),
    }


def _comp_summary(past, upcoming):
    """Per-competition played/remaining counts, for the fixtures page filters."""
    names = sorted({e["comp"] for e in past + upcoming},
                   key=lambda n: COMP_ORDER.get(n, 99))
    out = []
    for n in names:
        played = [e for e in past if e["comp"] == n]
        out.append({
            "comp": n,
            "comp_code": next((e["comp_code"] for e in past + upcoming if e["comp"] == n), n[:3]),
            "comp_slug": next((e["comp_slug"] for e in past + upcoming if e["comp"] == n), "pl"),
            "played": len(played),
            "upcoming": len([e for e in upcoming if e["comp"] == n]),
            "w": len([e for e in played if e["result"] == "W"]),
            "d": len([e for e in played if e["result"] == "D"]),
            "l": len([e for e in played if e["result"] == "L"]),
        })
    return out


def _is_matchday(nxt, live, now):
    if live:
        return True
    if not nxt:
        return False
    ko = datetime.fromisoformat(nxt["kickoff"])
    return ko.date() == now.date()


def refresh(conn=None, max_age_minutes=None):
    """Build the snapshot and cache it. Safe to call every scrape.

    The scraper now runs every 30 minutes rather than four times a day, and each
    build makes several sliced ESPN requests. Fixtures and league tables do not
    change that fast, so skip the rebuild while the cache is still warm. Pass
    max_age_minutes=0 to force a refresh."""
    own = conn is None
    if own:
        ctx = db.get_conn()
        conn = ctx.__enter__()
    try:
        if max_age_minutes:
            cached = get_cached(conn)
            updated = (cached or {}).get("_updated_at")
            if updated:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(updated)
                    if age < timedelta(minutes=max_age_minutes):
                        return cached
                except ValueError:
                    pass
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
    if snap.get("error"):
        print("ERROR:", snap["error"])
    else:
        for c in snap["comps"]:
            print(f"{c['comp_code']:>4}  played {c['played']}  next {c['upcoming']}  "
                  f"{c['w']}W {c['d']}D {c['l']}L")
        print("\nnext:", (snap["next_match"] or {}).get("comp"),
              (snap["next_match"] or {}).get("home"), "v", (snap["next_match"] or {}).get("away"))
        print("form:", "".join(snap["form"]))
        print("fixtures:", len(snap["fixtures"]), " results:", len(snap["results"]),
              " table rows:", len(snap["table"]))
