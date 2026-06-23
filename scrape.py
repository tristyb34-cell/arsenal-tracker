"""Arsenal Tracker scraper.

For each configured source:
  - skip if it's resting (too many consecutive fails this is not, handled inline)
  - conditional GET via ETag / Last-Modified (304 => nothing new, cheap)
  - polite User-Agent + random delay between sources
  - normalise entries, apply Arsenal relevance filter for general feeds
  - filter by recency, dedupe by URL hash + fuzzy title
  - categorise (rules + claude fallback) and store

Run: ./venv/bin/python scrape.py
"""

import html
import random
import re
import socket
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import feedparser

import alerts
import brief
import config
import db
import fixtures
from categorise import categorise_items
from enrich import extract_players

socket.setdefaulttimeout(config.REQUEST_TIMEOUT)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^a-z0-9 ]+")
_URL_RE = re.compile(r"https?://\S+")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    txt = _TAG_RE.sub(" ", raw)
    txt = html.unescape(txt)
    txt = _URL_RE.sub("", txt)
    return _WS_RE.sub(" ", txt).strip()


def title_key(title: str) -> str:
    """Normalised key for fuzzy dedupe: lowercase, alphanumeric words only."""
    t = _NONWORD_RE.sub(" ", (title or "").lower())
    return _WS_RE.sub(" ", t).strip()


def parsed_to_iso(entry):
    for attr in ("published_parsed", "updated_parsed"):
        tt = entry.get(attr)
        if tt:
            try:
                return datetime(*tt[:6], tzinfo=timezone.utc).isoformat()
            except (ValueError, TypeError):
                continue
    return None


def similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def fetch_source(src, conn):
    """Fetch one feed. Returns (list_of_raw_items, status_string)."""
    state = db.get_feed_state(conn, src["name"])
    etag = state["etag"] if state else None
    modified = state["modified"] if state else None
    fail_count = state["fail_count"] if state else 0

    try:
        d = feedparser.parse(
            src["url"],
            etag=etag,
            modified=modified,
            agent=config.USER_AGENT,
        )
    except Exception as e:
        fail_count += 1
        db.save_feed_state(conn, src["name"], etag, modified, fail_count,
                           now_iso(), f"error: {type(e).__name__}")
        return [], f"ERROR ({type(e).__name__})"

    status = getattr(d, "status", None)

    if status == 304:
        db.save_feed_state(conn, src["name"], etag, modified, 0,
                           now_iso(), "304 not-modified")
        return [], "304 not-modified"

    if not d.entries:
        # treat as soft fail (could be a transient block or dead mirror)
        fail_count += 1
        db.save_feed_state(conn, src["name"], etag, modified, fail_count,
                           now_iso(), f"empty (HTTP {status})")
        return [], f"EMPTY (HTTP {status})"

    new_etag = getattr(d, "etag", etag)
    new_modified = getattr(d, "modified", modified)
    db.save_feed_state(conn, src["name"], new_etag, new_modified, 0,
                       now_iso(), f"ok (HTTP {status})")

    raw_items = []
    for entry in d.entries[: config.MAX_ENTRIES_PER_SOURCE]:
        url = entry.get("link", "").strip()
        title = clean_text(entry.get("title", ""))
        if not url or not title:
            continue
        summary = clean_text(entry.get("summary", entry.get("description", "")))[:600]
        raw_items.append(
            {
                "url": url,
                "title": title,
                "summary": summary,
                "source": src["name"],
                "tier": src["tier"],
                "credibility": src["credibility"],
                "arsenal_feed": src["arsenal_feed"],
                "published_at": parsed_to_iso(entry),
            }
        )
    return raw_items, f"OK ({len(raw_items)} entries, HTTP {status})"


def run():
    db.init_db()
    started = now_iso()
    print(f"\n=== Arsenal Tracker scrape @ {started} ===")

    with db.get_conn() as conn:
        recency_cutoff = (datetime.now(timezone.utc)
                          - timedelta(days=config.RECENCY_DAYS)).isoformat()
        fuzzy_cutoff = (datetime.now(timezone.utc)
                        - timedelta(days=config.FUZZY_DEDUPE_DAYS)).isoformat()

        # load recent items for fuzzy dedupe + story clustering
        recent_rows = db.recent_cluster_rows(conn, fuzzy_cutoff)
        # cluster pool: list of {title, cluster_id, source}
        cluster_pool = [{"title": r["title"], "cluster_id": r["cluster_id"],
                         "source": r["source"]} for r in recent_rows]

        # 1. gather candidates across all sources
        candidates = []
        for src in config.SOURCES:
            state = db.get_feed_state(conn, src["name"])
            if state and state["fail_count"] >= config.BACKOFF_AFTER_FAILS:
                # rest this source for one cycle, then allow a retry next time
                print(f"  - {src['name']:22} RESTING (backoff), will retry next cycle")
                db.save_feed_state(conn, src["name"], state["etag"],
                                   state["modified"], 0, now_iso(), "rested")
                continue

            raw_items, status = fetch_source(src, conn)
            conn.commit()
            print(f"  - {src['name']:22} {status}")

            for it in raw_items:
                text = f"{it['title']}. {it['summary']}"
                # recency filter (keep undated items)
                if it["published_at"] and it["published_at"] < recency_cutoff:
                    continue
                # tag tracked clubs; Arsenal feeds are always Arsenal
                clubs = config.tag_clubs(text)
                if it["arsenal_feed"] and "Arsenal" not in clubs:
                    clubs.insert(0, "Arsenal")
                # coarse relevance gate: must touch a tracked club
                if not clubs:
                    continue
                it["text"] = text
                it["clubs"] = clubs
                candidates.append(it)

            time.sleep(random.uniform(config.MIN_DELAY, config.MAX_DELAY))

        # 2. dedupe (drop true duplicates) + cluster (link cross-source variants)
        fresh = []
        for it in candidates:
            uh = db.url_hash(it["url"])
            if db.item_exists(conn, uh):
                continue
            tk = title_key(it["title"])

            # find the best-matching existing/accepted story
            best_sim, best = 0.0, None
            for cand in cluster_pool:
                s = similar(it["title"], cand["title"])
                if s > best_sim:
                    best_sim, best = s, cand

            # same source + near-identical title => true duplicate, drop
            if best and best_sim >= config.FUZZY_THRESHOLD and best["source"] == it["source"]:
                continue

            if best and best_sim >= config.CLUSTER_THRESHOLD:
                cluster_id = best["cluster_id"]          # join existing story
            else:
                cluster_id = uuid.uuid4().hex            # new story

            it["url_hash"] = uh
            it["title_key"] = tk
            it["cluster_id"] = cluster_id
            fresh.append(it)
            cluster_pool.append({"title": it["title"], "cluster_id": cluster_id,
                                 "source": it["source"]})

        print(f"  -> {len(candidates)} relevant, {len(fresh)} new after dedupe/cluster")

        # 3. categorise (rules + claude fallback), then extract players (transfers)
        categorise_items(fresh)
        claude_n = sum(1 for it in fresh if it["category_by"] == "claude")
        extract_players(fresh)
        named = sum(1 for it in fresh if it.get("player"))
        print(f"  -> categorised ({claude_n} via claude), {named} players named")

        # 4. route to a page + score transfer likelihood, then store
        stamp = now_iso()
        stored = {"arsenal": 0, "europe": 0}
        stored_items = []
        for it in fresh:
            arsenal_tagged = it["arsenal_feed"] or "Arsenal" in it["clubs"]
            is_transfer = it["category"] == "Transfers"

            if arsenal_tagged:
                page = "arsenal"
            elif is_transfer:
                page = "europe"          # rival/European transfer story
            else:
                continue                  # other-club non-transfer: not wanted

            likelihood, likelihood_by = (None, None)
            if is_transfer:
                likelihood, likelihood_by = config.assess_likelihood(
                    it["title"], it["credibility"]
                )

            # on the Europe page we don't want Arsenal in the club list
            club_list = [c for c in it["clubs"] if not (page == "europe" and c == "Arsenal")]

            record = {
                "url_hash": it["url_hash"],
                "url": it["url"],
                "title": it["title"],
                "title_key": it["title_key"],
                "summary": it["summary"],
                "source": it["source"],
                "tier": it["tier"],
                "credibility": it["credibility"],
                "page": page,
                "clubs": ", ".join(club_list),
                "player": it.get("player", ""),
                "cluster_id": it["cluster_id"],
                "category": it["category"],
                "category_by": it["category_by"],
                "likelihood": likelihood,
                "likelihood_by": likelihood_by,
                "published_at": it["published_at"],
                "first_seen": stamp,
            }
            db.insert_item(conn, record)
            stored[page] += 1
            stored_items.append(record)

        # 5. native alerts for the big moments
        fired = alerts.process(conn, stored_items)
        if fired:
            print(f"  -> fired {fired} notification(s)")

    # 6. refresh football snapshot + morning brief (outside the write loop)
    with db.get_conn() as conn:
        fx = fixtures.refresh(conn)
        if "error" in fx:
            print(f"  -> fixtures refresh failed: {fx['error']}")
        else:
            nm = fx.get("next_match")
            print(f"  -> football refreshed (next: {nm['away'] if nm else 'TBA'})")
        brief.refresh_if_stale(conn)
        print("  -> morning brief refreshed")

    print(f"=== done: stored {stored['arsenal']} Arsenal + {stored['europe']} Europe items ===")
    return stored


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(130)
