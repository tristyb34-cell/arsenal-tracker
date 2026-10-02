"""Arsenal fixtures, results, form, and the league tables via ESPN's free public
API (no key).

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

TEAM = "Arsenal"
TEAM_ID = "359"
# One team schedule across every competition. This replaced per-competition
# scoreboard slices on 2026-10-02: ESPN began answering any `dates=A-B` range
# with HTTP 400, the old fetcher swallowed it, and the published fixtures list
# sat empty from 16 Sep while the log still said "football refreshed".
SCHEDULE = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{TEAM_ID}/schedule"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/{league}/standings"

# ESPN league slug, display name, short badge, css slug. Anything else ESPN
# returns for Arsenal (club.friendly, friendly.emirates_cup) is pre-season and
# deliberately left out of the season record.
COMPS = [
    ("eng.1", "Premier League", "PL", "pl"),
    ("uefa.champions", "Champions League", "UCL", "ucl"),
    ("eng.fa", "FA Cup", "FA", "fa"),
    ("eng.league_cup", "Carabao Cup", "EFL", "efl"),
    ("eng.charity", "Community Shield", "CS", "cs"),
    ("uefa.super_cup", "Super Cup", "USC", "usc"),
]
COMP_BY_LEAGUE = {c[0]: c for c in COMPS}
COMP_ORDER = {c[1]: i for i, c in enumerate(COMPS)}

# A kicked-off match the feed has not flagged live yet stays on the fixtures
# list for this long, rather than vanishing until ESPN calls it finished.
GRACE = timedelta(hours=3)


def _get(url, params=None):
    # ESPN 403'd browser-spoofed UAs from 2026-08-04. Plain requests UA works.
    r = requests.get(url, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _season_start(now):
    """European seasons run July to June. Anything before 1 July belongs to the
    previous campaign and must not count towards this season's record or form."""
    year = now.year if now.month >= 7 else now.year - 1
    return datetime(year, 7, 1, tzinfo=timezone.utc)


def _arsenal_events():
    """Every competitive Arsenal match this season, results and fixtures.

    Raises if ESPN fails or returns nothing, so refresh() keeps the last good
    cache instead of overwriting it with an empty season."""
    start = _season_start(datetime.now(timezone.utc))
    seen = {}
    for params in ({}, {"fixture": "true"}):  # results, then upcoming
        for e in _get(SCHEDULE, params).get("events", []):
            comp = COMP_BY_LEAGUE.get((e.get("league") or {}).get("slug", ""))
            ev = _parse_event(e, comp) if comp else None
            if ev and datetime.fromisoformat(ev["kickoff"]) >= start:
                seen[ev["id"]] = ev
    if not seen:
        raise RuntimeError("ESPN schedule returned no competitive Arsenal matches")
    return sorted(seen.values(), key=lambda x: x["kickoff"])


def _parse_event(e, comp):
    league, comp_name, comp_code, comp_slug = comp
    try:
        c = e["competitions"][0]
        home = next(t for t in c["competitors"] if t["homeAway"] == "home")
        away = next(t for t in c["competitors"] if t["homeAway"] == "away")
        st = c["status"]
        ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
    except (KeyError, IndexError, StopIteration, ValueError):
        return None
    stype = st.get("type") or {}
    return {
        "id": str(e.get("id", ko.isoformat())),
        "league": league,
        "url": _event_url(e),
        "kickoff": ko.isoformat(),
        "comp": comp_name,
        "comp_code": comp_code,
        "comp_slug": comp_slug,
        "round": _round(e),
        "note": ((c.get("notes") or [{}])[0] or {}).get("headline", ""),
        "venue": (c.get("venue") or {}).get("fullName", ""),
        "home": home["team"]["displayName"],
        "away": away["team"]["displayName"],
        "home_short": home["team"].get("abbreviation", ""),
        "away_short": away["team"].get("abbreviation", ""),
        # "Brighton" rather than "Brighton & Hove Albion" where space is tight
        "home_name": home["team"].get("shortDisplayName") or home["team"]["displayName"],
        "away_name": away["team"].get("shortDisplayName") or away["team"]["displayName"],
        "home_logo": _logo(home["team"]),
        "away_logo": _logo(away["team"]),
        "home_goals": _score(home.get("score")),
        "away_goals": _score(away.get("score")),
        "finished": bool(stype.get("completed")),
        "live": stype.get("state") == "in",
        "status": stype.get("shortDetail", ""),
        "status_name": stype.get("name", ""),
        "clock": st.get("clock"),
        "display_clock": st.get("displayClock", ""),
        "period": st.get("period"),
        "clock_at": datetime.now(timezone.utc).isoformat(),
    }


def _round(e):
    """Cup ties carry the round in seasonType ("Third Round", "League Phase").
    League games carry the season name there instead, which is not a round."""
    name = (e.get("seasonType") or {}).get("name", "") or ""
    return "" if name[:4].isdigit() else name


def _logo(team):
    for lg in team.get("logos") or []:
        if "default" in (lg.get("rel") or []) and lg.get("href"):
            return lg["href"]
    return team.get("logo", "") or ((team.get("logos") or [{}])[0] or {}).get("href", "")


def _score(v):
    """The schedule endpoint sends `{"value": 3.0, "displayValue": "3"}`, the
    scoreboard sends a bare "3", and an unplayed match sends nothing."""
    if isinstance(v, dict):
        v = v.get("displayValue", v.get("value"))
    return _maybe_int(v)


def _event_url(e):
    """ESPN's own match page, so a fixture row has somewhere to go."""
    for link in e.get("links", []):
        href = link.get("href", "")
        if href.startswith("http") and "desktop" in link.get("rel", []):
            return href
    return ""


def _maybe_int(v):
    try:
        return int(float(v))
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
    ev["opponent_name"] = (ev.get("away_name") if ars_home else ev.get("home_name")) or ev["opponent"]
    ev["home_away"] = "H" if ars_home else "A"
    ev["result"] = _result_for_arsenal(ev)
    if ev["home_goals"] is not None and ev["away_goals"] is not None:
        ev["score"] = (f"{ev['home_goals']}–{ev['away_goals']}" if ars_home
                       else f"{ev['away_goals']}–{ev['home_goals']}")
    else:
        ev["score"] = ""
    return ev


def _standings_rows(league="eng.1"):
    entries = _find_entries(_get(STANDINGS.format(league=league)))
    table = []
    for e in entries or []:
        stats = {s["name"]: s.get("displayValue") for s in e.get("stats", [])}
        t = e["team"]
        table.append({
            "rank": _maybe_int(stats.get("rank")),
            "team": t["displayName"],
            "team_short": t.get("abbreviation", ""),
            "short_name": t.get("shortDisplayName") or t["displayName"],
            "logo": _logo(t),
            "played": stats.get("gamesPlayed"),
            "w": stats.get("wins"),
            "d": stats.get("ties"),
            "l": stats.get("losses"),
            "gf": stats.get("pointsFor"),
            "ga": stats.get("pointsAgainst"),
            "points": stats.get("points"),
            "gd": stats.get("pointDifferential") or stats.get("goalDifference"),
            # qualification / relegation band, coloured by ESPN
            "zone": (e.get("note") or {}).get("description", ""),
            "zone_colour": (e.get("note") or {}).get("color", ""),
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


def assemble(events, table, ucl_table=None, now=None):
    """Shape decorated events and tables into the dashboard's football block."""
    now = now or datetime.now(timezone.utc)
    events = sorted(events, key=lambda x: x["kickoff"])
    past = [e for e in events if e["finished"]]
    live = [e for e in events if e["live"]]
    upcoming = [e for e in events
                if not e["finished"] and not e["live"]
                and datetime.fromisoformat(e["kickoff"]) >= now - GRACE]

    last = past[-1] if past else None
    nxt = upcoming[0] if upcoming else None
    form = [r for r in (_result_for_arsenal(e) for e in past[-5:]) if r]
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
        "ucl_table": ucl_table or [],
        "is_matchday": _is_matchday(nxt, live, now),
    }


def build_snapshot():
    """Fetch everything and assemble the dashboard's football snapshot."""
    events = [_decorate(e) for e in _arsenal_events()]
    ucl = []
    if any(e["league"] == "uefa.champions" for e in events):
        try:
            ucl = _standings_rows("uefa.champions")
        except Exception:
            ucl = []  # the league table still matters more than this one
    return assemble(events, _standings_rows("eng.1"), ucl)


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


def apply_live(snap, event_id, state):
    """Patch one match's status in the cached snapshot from a fresher source.

    The fixtures cache is rebuilt every 90 minutes, which is a whole match. The
    match centre summary is polled every minute while a game is on, so its
    header is the best truth for score and clock; export.py feeds it back here
    so Home, Matches and the match centre never disagree."""
    if not snap or not state:
        return snap
    events = {}
    for bucket in ("results", "fixtures"):
        for e in snap.get(bucket) or []:
            events[str(e["id"])] = e
    live = snap.get("live_match")
    if live:
        events.setdefault(str(live["id"]), live)
    ev = events.get(str(event_id))
    if not ev:
        return snap
    ev.update({
        "live": state["state"] == "in",
        "finished": bool(state["completed"]),
        "home_goals": state["home_goals"],
        "away_goals": state["away_goals"],
        "status": state.get("detail") or ev.get("status", ""),
        "status_name": state.get("name", ""),
        "clock": state.get("clock"),
        "display_clock": state.get("display_clock", ""),
        "period": state.get("period"),
        "clock_at": state.get("clock_at") or ev.get("clock_at"),
    })
    _decorate(ev)
    patched = assemble([_decorate(dict(e)) for e in events.values()],
                       snap.get("table") or [], snap.get("ucl_table"))
    keep = {k: v for k, v in snap.items() if k.startswith("_")}
    return {**patched, **keep}


def refresh(conn=None, max_age_minutes=None):
    """Build the snapshot and cache it. Safe to call every scrape.

    The scraper now runs every 30 minutes rather than four times a day, and each
    build makes several ESPN requests. Fixtures and league tables do not change
    that fast, so skip the rebuild while the cache is still warm. Pass
    max_age_minutes=0 to force a refresh. On any failure the previous cache is
    left exactly as it was."""
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
              " table rows:", len(snap["table"]), " ucl rows:", len(snap["ucl_table"]))
