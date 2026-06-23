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
from datetime import datetime, timezone

import brief
import config
import db
import fixtures

OUT_DIR = os.path.join(config.BASE_DIR, "docs", "data")
OUT_FILE = os.path.join(OUT_DIR, "snapshot.json")

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


def _sagas(conn):
    """Per-player transfer timelines, merged across both pages, for the saga view."""
    players = set(db.distinct_players(conn, page="arsenal")) | \
        set(db.distinct_players(conn, page="europe"))
    keys = ("title", "url", "source", "credibility", "likelihood")
    sagas = {}
    for p in players:
        rows = list(db.saga(conn, p, page="arsenal")) + list(db.saga(conn, p, page="europe"))
        rows.sort(key=lambda r: r["ts"] if "ts" in r.keys() else "")
        sagas[p] = _rows(rows, keys)
    return sagas


def build(conn):
    deal_keys = ("title", "url", "source", "player", "clubs")
    inj_keys = ("title", "url", "source", "player")

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
        "football": fixtures.get_cached(conn),
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
        "sagas": _sagas(conn),
    }
    return snap


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with db.get_conn() as conn:
        snap = build(conn)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(OUT_FILE) / 1024
    print(f"Wrote {OUT_FILE} ({size_kb:.0f} KB) at {snap['generated_at']}")


if __name__ == "__main__":
    main()
