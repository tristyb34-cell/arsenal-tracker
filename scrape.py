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
    """Normalised key for fuzzy dedupe: lowercase, alphanumeric words only.

    Accents are folded FIRST. Without that, "Vinícius Júnior" shredded into
    "vin cius j nior" and never matched "Vinicius Junior", so the same saga
    clustered twice depending on whether the outlet used accents."""
    t = (title or "").lower().translate(config._ACCENTS)
    t = _NONWORD_RE.sub(" ", t)
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


# Words that carry no story identity, so they never count towards clustering.
_CLUSTER_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "his", "her", "its",
    "are", "was", "were", "has", "have", "had", "will", "would", "could",
    "after", "over", "into", "out", "off", "but", "not", "who", "how", "why",
    "what", "when", "new", "says", "say", "said", "amid", "ahead", "set",
    "transfer", "transfers", "news", "latest", "update", "updates", "report",
    "reports", "live", "star", "man", "boss", "club", "deal", "move", "summer",
    # saga filler: present in half the headlines of any long-running story
    "boost", "twist", "hope", "hopes", "claim", "claims", "verdict", "stance",
    "reaction", "opinion", "blow", "hint", "hints", "dream", "saga", "pursuit",
    "chase", "race", "plan", "plans", "decision", "response", "message",
    "admission", "future", "player", "signing", "target", "interest", "window",
}

# Club names are constant across a saga (every Guimaraes headline says
# "Newcastle"), so they identify the saga, not the story. Stripped for the same
# reason as the player name.
_CLUB_WORDS = {
    w
    for terms in list(config.CLUB_TERMS.values()) + [config.OTHER_CLUB_TERMS]
    for t in terms
    for w in t.lower().replace("-", " ").split()
    if len(w) > 2
}


def content_tokens(title: str) -> set:
    """Identity-bearing words of a headline (names, clubs, verbs)."""
    return {w for w in title_key(title).split()
            if len(w) > 2 and w not in _CLUSTER_STOPWORDS}


def story_tokens(title: str, player: str = "") -> set:
    """Content words MINUS the ones every item in a saga shares.

    A saga is not a story. Ninety Vinicius headlines all contain "vinicius" and
    "arsenal", so scoring on raw content words merged an entire transfer saga
    into one cluster, and the feed then stamped the whole thing with the highest
    rung any member had reached: a speculative "Could Vinicius really be heading
    to Arsenal?" card displaying HERE WE GO. Dropping the player and club names
    forces the match to come from what actually happened (medical, bid, agree)."""
    drop = set(title_key(player).split()) | _CLUB_WORDS
    return {w for w in content_tokens(title) if w not in drop}


def overlap(a: set, b: set) -> float:
    """Overlap coefficient: shared words over the SHORTER headline.

    Jaccard punishes the length gap between a terse insider tweet and a 15-word
    football.london headline about the same story, which is exactly the pair we
    most want to link. Containment does not. Requires a minimum number of shared
    words so two three-word stubs cannot score 1.0 on a single coincidence."""
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if shared < config.CLUSTER_MIN_SHARED:
        return 0.0
    return shared / min(len(a), len(b))


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
        cluster_pool = [{"title": r["title"], "cluster_id": r["cluster_id"],
                         "source": r["source"], "player": r["player"] or "",
                         "tokens": content_tokens(r["title"])}
                        for r in recent_rows]

        # players Arsenal are actively linked with, derived from headlines that
        # explicitly name the club. Lets "Bruno Guimaraes deal done" reach the
        # Arsenal tab even though the headline never says "Arsenal".
        orbit = db.arsenal_orbit_players(conn, days=config.ORBIT_DAYS)

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
                # women's football is out of scope entirely, drop at ingest
                if config.is_womens(text):
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

        # 2. dedupe: drop URLs we already have, then same-source near-identical
        #    titles (a genuine repost rather than a second outlet's take)
        fresh = []
        for it in candidates:
            uh = db.url_hash(it["url"])
            if db.item_exists(conn, uh):
                continue
            it["tokens"] = content_tokens(it["title"])

            dupe = any(
                cand["source"] == it["source"]
                and similar(it["title"], cand["title"]) >= config.FUZZY_THRESHOLD
                for cand in cluster_pool
            )
            if dupe:
                continue

            it["url_hash"] = uh
            it["title_key"] = title_key(it["title"])
            fresh.append(it)
            # provisional pool entry so same-run duplicates are caught too
            cluster_pool.append({"title": it["title"], "cluster_id": None,
                                 "source": it["source"], "player": "",
                                 "tokens": it["tokens"]})

        print(f"  -> {len(candidates)} relevant, {len(fresh)} new after dedupe")

        # 3. categorise (rules + claude fallback), then extract players (transfers).
        #    This runs BEFORE clustering because the canonical player name is the
        #    strongest signal for linking two outlets' takes on the same story.
        categorise_items(fresh)
        claude_n = sum(1 for it in fresh if it["category_by"] == "claude")
        extract_players(fresh)
        named = sum(1 for it in fresh if it.get("player"))
        print(f"  -> categorised ({claude_n} via claude), {named} players named")

        # 3b. cluster: link cross-source variants of one story.
        #     The old version compared raw titles with SequenceMatcher at 0.72,
        #     which two outlets' phrasings never reach: 136 items produced 136
        #     clusters, so "N sources agree" never fired. Word overlap plus a
        #     shared player name is what actually identifies one story.
        pool = [c for c in cluster_pool if c["cluster_id"]]
        for c in pool:
            c["tokens"] = story_tokens(c["title"], c["player"])
        for it in fresh:
            player = it.get("player", "")
            tokens = story_tokens(it["title"], player)
            best_score, best = 0.0, None
            for cand in pool:
                # two headlines about different players are different stories,
                # however similar the wording
                if player and cand["player"] and cand["player"] != player:
                    continue
                score = overlap(tokens, cand["tokens"])
                need = (config.CLUSTER_THRESHOLD if player and cand["player"] == player
                        else config.CLUSTER_THRESHOLD_NO_PLAYER)
                if score >= need and score > best_score:
                    best_score, best = score, cand

            it["cluster_id"] = best["cluster_id"] if best else uuid.uuid4().hex
            pool.append({"title": it["title"], "cluster_id": it["cluster_id"],
                         "source": it["source"], "player": player,
                         "tokens": tokens})
        linked = sum(1 for it in fresh if any(
            o is not it and o.get("cluster_id") == it["cluster_id"] for o in fresh))
        print(f"  -> clustered ({linked} of {len(fresh)} linked to another story)")

        # 4. route to a page + score transfer likelihood, then store
        stamp = now_iso()
        stored = {"arsenal": 0, "europe": 0}
        stored_items = []
        dropped = []            # what the routing gate rejected, and why
        for it in fresh:
            is_transfer = it["category"] == "Transfers"
            title = it["title"]
            # Arsenal signal is read from the TITLE, never the summary. Gossip
            # round-ups ("Tuesday's gossip") name ten clubs in the summary, which
            # is how "Man City brace for Rodri bid" ended up on the Arsenal tab.
            signal = config.arsenal_signal(title)
            rivals_in_title = [c for c in config.tag_clubs(title) if c != "Arsenal"]
            other_club = config.names_other_club(title)

            if is_transfer:
                # The Arsenal tab is Arsenal transfers only. Earn it by naming
                # the club, naming one of our players, or naming a player we are
                # currently linked with in a headline that isn't plainly about
                # someone else's business. Without that last guard the orbit
                # drags in "Atletico CEO on Alvarez and Barcelona": an orbit
                # player, but not remotely an Arsenal story.
                orbit_hit = (it.get("player") in orbit and not other_club)
                if signal or orbit_hit:
                    page = "arsenal"
                else:
                    page = "europe"      # rival/European transfer story
            else:
                # Non-transfer Arsenal-feed content is Arsenal by default, unless
                # the headline is plainly about a rival instead.
                if signal or (it["arsenal_feed"] and not rivals_in_title):
                    page = "arsenal"
                else:
                    # other-club non-transfer: not wanted
                    dropped.append((it["source"], title))
                    continue

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

        # The routing gate is deliberately strict, so log what it rejected.
        # A silent drop is indistinguishable from a scraper that found nothing.
        if dropped:
            print(f"  -> dropped {len(dropped)} off-topic (not Arsenal, not a transfer):")
            for src, t in dropped[:8]:
                print(f"       {src}: {t[:74]}")

        # 5. native alerts for the big moments
        fired = alerts.process(conn, stored_items)
        if fired:
            print(f"  -> fired {fired} notification(s)")

    # 6. refresh football snapshot + morning brief (outside the write loop)
    with db.get_conn() as conn:
        fx = fixtures.refresh(conn, max_age_minutes=config.FIXTURES_MAX_AGE_MINUTES)
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
