"""Export the live DB to a single static snapshot.json for the PWA.

The Mac keeps scraping into arsenal.db as normal. This reads that DB through the
same db.py query helpers the Flask app uses, then writes docs/data/snapshot.json.
The static frontend (docs/) fetches that file and renders everything client-side,
so the app can live on GitHub Pages and install on a phone. Read-only: this never
writes to the DB.

Run standalone or via run_scrape.sh after each scrape.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import brief
import config
import db
import fixtures
import matchcentre

OUT_DIR = os.path.join(config.BASE_DIR, "docs", "data")
OUT_FILE = os.path.join(OUT_DIR, "snapshot.json")
SAGAS_FILE = os.path.join(OUT_DIR, "sagas.json")
MATCH_DIR = os.path.join(OUT_DIR, "match")

# Same window live_alerts.py polls in: the lineup drop to well past full time.
WINDOW_BEFORE = timedelta(minutes=75)
WINDOW_AFTER = timedelta(minutes=180)

# Fields we keep per cluster (trim the row to what the cards actually render).
CLUSTER_FIELDS = (
    "url_hash", "url", "title", "summary", "source", "category",
    "clubs", "player", "best_likelihood", "has_insider",
    "source_count", "sources_list",
)


def _ts(row):
    keys = row.keys()
    if "ts" in keys:
        return row["ts"]
    return row["published_at"] or row["first_seen"]


def _cluster(c):
    out = {k: c.get(k) for k in CLUSTER_FIELDS}
    # cards only render the first 200 chars; trim to keep the payload small
    if out.get("summary"):
        out["summary"] = out["summary"][:210]
    out["ts"] = _ts(c)
    return out


def _rows(rows, keys):
    """sqlite Rows -> list of trimmed dicts, with a unified ts field."""
    out = []
    for r in rows:
        d = {k: r[k] for k in keys}
        d["ts"] = _ts(r)
        out.append(d)
    return out


def _insiders(conn):
    out = []
    for name in config.INSIDER_SOURCES:
        out.append({"name": name.replace(" (X)", ""),
                    "last": db.insider_last_post(conn, name)})
    out.sort(key=lambda x: x["last"] or "", reverse=True)
    return out


def sagas(conn):
    """Per-player transfer timelines, merged across both pages, for the saga view.

    Written to its own file: at ~460 KB it was nearly half the snapshot, and the
    phone downloaded it every five minutes to show on a page it rarely opens."""
    players = set(db.distinct_players(conn, page="arsenal")) | \
        set(db.distinct_players(conn, page="europe"))
    keys = ("title", "url", "source", "credibility", "likelihood")
    out = {}
    for p in players:
        rows = list(db.saga(conn, p, page="arsenal")) + list(db.saga(conn, p, page="europe"))
        rows.sort(key=lambda r: r["ts"] if "ts" in r.keys() else "")
        out[p] = _rows(rows, keys)
    return out


def _match_events(football):
    """Every match worth a match centre: all results, the live one, the next."""
    out = {}
    for e in list(football.get("results") or []) + \
            [football.get(k) for k in ("live_match", "next_match")]:
        if e:
            out[str(e["id"])] = e
    return out


def _current(football, now):
    """The match in its live window right now, if any."""
    for e in [football.get("live_match"), football.get("next_match"),
              football.get("last_result")]:
        if not e:
            continue
        try:
            ko = datetime.fromisoformat(e["kickoff"])
        except (KeyError, ValueError):
            continue
        if ko - WINDOW_BEFORE <= now <= ko + WINDOW_AFTER:
            return e
    return None


def football_and_matches(conn):
    """The fixtures block with any live match patched in, plus every match
    centre payload keyed by event id.

    ESPN's schedule is cached for 90 minutes, which is longer than a match, so
    while a game is in its window the match centre summary (polled every
    minute by live_alerts) supplies the score and clock instead."""
    football = fixtures.get_cached(conn) or {}
    payloads = {}
    for eid, ev in _match_events(football).items():
        payload = matchcentre.get(conn, ev)
        if payload:
            payloads[eid] = payload
    cur = _current(football, datetime.now(timezone.utc))
    if cur and (payloads.get(str(cur["id"])) or {}).get("status"):
        football = fixtures.apply_live(football, cur["id"], payloads[str(cur["id"])]["status"])
    return football, payloads


def _embedded(football, payloads):
    """The payloads Home needs instantly (live, next, last). The rest are
    written as one file per match and fetched when opened."""
    keep = {str(football[k]["id"]) for k in ("live_match", "next_match", "last_result")
            if football.get(k)}
    return {k: v for k, v in payloads.items() if k in keep}


def write_match_files(payloads):
    """docs/data/match/<id>.json, rewritten only when the content changed so a
    finished match does not churn a commit every 30 minutes."""
    os.makedirs(MATCH_DIR, exist_ok=True)
    for eid, payload in payloads.items():
        path = os.path.join(MATCH_DIR, f"{eid}.json")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == body:
                    continue
        except FileNotFoundError:
            pass
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)


def build(conn, football=None, payloads=None):
    deal_keys = ("title", "url", "source", "player", "clubs")
    inj_keys = ("title", "url", "source", "player")
    if football is None:
        football, payloads = football_and_matches(conn)

    snap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_scrape": db.last_scrape_time(conn),
        "meta": {
            "categories": config.CATEGORY_ORDER,
            "rungs": config.LIKELIHOOD_RUNGS,
            "europe_clubs_order": config.EUROPE_CLUBS_ORDER,
            "club_codes": config.CLUB_CODES,
            "club_crests": config.CLUB_CRESTS,
        },
        "brief": brief.get_cached(conn),
        "football": football,
        "insiders": _insiders(conn),
        "arsenal": {
            "clusters": [_cluster(c) for c in db.query_clusters(conn, page="arsenal")],
            "sources": db.distinct_sources(conn, page="arsenal"),
        },
        "all": {
            "clusters": [_cluster(c) for c in db.query_clusters(conn, page="all", limit=400)],
            "sources": db.distinct_sources(conn, page="all"),
        },
        "europe": {
            "clusters": [_cluster(c) for c in db.query_clusters(conn, page="europe", limit=500)],
            "club_counts": db.europe_club_counts(conn),
        },
        "heat": {
            "arsenal": db.heat_page(conn, page="arsenal"),
            "europe": db.heat_page(conn, page="europe"),
            "all": db.heat_page(conn, page="all"),
        },
        "deals": {
            "arsenal": _rows(db.done_deals(conn, page="arsenal"), deal_keys),
            "all": _rows(db.done_deals(conn, page="all"), deal_keys),
            "europe": _rows(db.done_deals(conn, page="europe"), deal_keys),
        },
        "injuries": _rows(db.injury_board(conn), inj_keys),
        "team_news": _rows(db.team_news(conn), ("title", "url", "source", "player", "ts")),
        "matches": _embedded(football, payloads or {}),
    }
    return snap


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with db.get_conn() as conn:
        football, payloads = football_and_matches(conn)
        snap = build(conn, football, payloads)
        saga_map = sagas(conn)
    write_match_files(payloads)
    with open(SAGAS_FILE, "w", encoding="utf-8") as f:
        json.dump(saga_map, f, ensure_ascii=False, separators=(",", ":"))
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(OUT_FILE) / 1024
    print(f"Wrote {OUT_FILE} ({size_kb:.0f} KB) at {snap['generated_at']}")


if __name__ == "__main__":
    main()
