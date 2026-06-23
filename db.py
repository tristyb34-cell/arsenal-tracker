"""SQLite storage for Arsenal Tracker.

Two tables:
  items       - one row per news item (deduped by URL hash)
  feed_state  - per-source ETag / Last-Modified for conditional requests,
                plus consecutive-fail counter for backoff.
"""

import hashlib
import sqlite3
from contextlib import contextmanager

import config


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash      TEXT UNIQUE NOT NULL,
                url           TEXT NOT NULL,
                title         TEXT NOT NULL,
                title_key     TEXT NOT NULL,
                summary       TEXT,
                source        TEXT NOT NULL,
                tier          INTEGER NOT NULL,
                credibility   TEXT,            -- insider/high/medium/low
                page          TEXT NOT NULL,   -- 'arsenal' or 'europe'
                clubs         TEXT,            -- comma-separated tracked clubs
                player        TEXT,            -- extracted player (transfers)
                cluster_id    TEXT,            -- story cluster (cross-source)
                category      TEXT NOT NULL,
                category_by   TEXT,            -- 'rules' or 'claude'
                likelihood    TEXT,            -- transfer rung (or NULL)
                likelihood_by TEXT,            -- 'rules' or 'rules+insider'
                published_at  TEXT,            -- ISO8601 from feed
                first_seen    TEXT NOT NULL    -- ISO8601 when we stored it
            );
            CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
            CREATE INDEX IF NOT EXISTS idx_items_category  ON items(category);
            CREATE INDEX IF NOT EXISTS idx_items_titlekey  ON items(title_key);
            CREATE INDEX IF NOT EXISTS idx_items_page      ON items(page);

            CREATE TABLE IF NOT EXISTS feed_state (
                source        TEXT PRIMARY KEY,
                etag          TEXT,
                modified      TEXT,
                fail_count    INTEGER NOT NULL DEFAULT 0,
                last_run      TEXT,
                last_status   TEXT
            );

            -- generic cache for fixtures / standings / morning brief (JSON or text)
            CREATE TABLE IF NOT EXISTS kv_cache (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT
            );

            -- de-dupe native notifications so we alert once per item
            CREATE TABLE IF NOT EXISTS alerts_sent (
                url_hash TEXT PRIMARY KEY,
                sent_at  TEXT
            );
            """
        )
        _migrate(conn)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);
            CREATE INDEX IF NOT EXISTS idx_items_player  ON items(player);
            """
        )


def _migrate(conn):
    """Add any columns/tables missing from an older DB (in-place upgrade)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    additions = {
        "credibility": "TEXT", "page": "TEXT", "clubs": "TEXT",
        "player": "TEXT", "cluster_id": "TEXT",
        "likelihood": "TEXT", "likelihood_by": "TEXT",
    }
    for col, typ in additions.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} {typ}")


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def item_exists(conn, uh: str) -> bool:
    cur = conn.execute("SELECT 1 FROM items WHERE url_hash = ? LIMIT 1", (uh,))
    return cur.fetchone() is not None


def find_recent_title_keys(conn, since_iso: str):
    """Return set of title_keys first seen since the given ISO timestamp."""
    cur = conn.execute(
        "SELECT title_key FROM items WHERE first_seen >= ?", (since_iso,)
    )
    return {row["title_key"] for row in cur.fetchall()}


def insert_item(conn, item: dict):
    conn.execute(
        """
        INSERT OR IGNORE INTO items
            (url_hash, url, title, title_key, summary, source, tier, credibility,
             page, clubs, player, cluster_id, category, category_by, likelihood,
             likelihood_by, published_at, first_seen)
        VALUES
            (:url_hash, :url, :title, :title_key, :summary, :source, :tier, :credibility,
             :page, :clubs, :player, :cluster_id, :category, :category_by, :likelihood,
             :likelihood_by, :published_at, :first_seen)
        """,
        item,
    )


# --- feed_state helpers ---

def get_feed_state(conn, source: str):
    cur = conn.execute("SELECT * FROM feed_state WHERE source = ?", (source,))
    return cur.fetchone()


def save_feed_state(conn, source, etag, modified, fail_count, last_run, last_status):
    conn.execute(
        """
        INSERT INTO feed_state (source, etag, modified, fail_count, last_run, last_status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            etag=excluded.etag,
            modified=excluded.modified,
            fail_count=excluded.fail_count,
            last_run=excluded.last_run,
            last_status=excluded.last_status
        """,
        (source, etag, modified, fail_count, last_run, last_status),
    )


# --- query helpers for the dashboard ---

def query_items(conn, page="arsenal", category=None, source=None, search=None,
                club=None, limit=400):
    sql = "SELECT * FROM items WHERE page = ?"
    params = [page]
    if category and category != "All":
        sql += " AND category = ?"
        params.append(category)
    if source and source != "All":
        sql += " AND source = ?"
        params.append(source)
    if club and club != "All":
        sql += " AND clubs LIKE ?"
        params.append(f"%{club}%")
    if search:
        sql += " AND (title LIKE ? OR summary LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    # newest first: prefer published_at, fall back to first_seen
    sql += " ORDER BY COALESCE(published_at, first_seen) DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def category_counts(conn, page="arsenal"):
    if page and page != "all":
        cur = conn.execute(
            "SELECT category, COUNT(*) c FROM items WHERE page = ? GROUP BY category",
            (page,),
        )
    else:
        cur = conn.execute("SELECT category, COUNT(*) c FROM items GROUP BY category")
    return {row["category"]: row["c"] for row in cur.fetchall()}


def europe_club_counts(conn):
    """Count Europe-page items per club (clubs column may list several)."""
    cur = conn.execute("SELECT clubs FROM items WHERE page = 'europe'")
    counts = {}
    for row in cur.fetchall():
        for club in (row["clubs"] or "").split(","):
            club = club.strip()
            if club:
                counts[club] = counts.get(club, 0) + 1
    return counts


def distinct_sources(conn, page="arsenal"):
    if page and page != "all":
        cur = conn.execute(
            "SELECT DISTINCT source FROM items WHERE page = ? ORDER BY source", (page,)
        )
    else:
        cur = conn.execute("SELECT DISTINCT source FROM items ORDER BY source")
    return [row["source"] for row in cur.fetchall()]


def insider_last_post(conn, source):
    """Most recent published/seen time for a given source (Fabrizio watch)."""
    cur = conn.execute(
        "SELECT MAX(COALESCE(published_at, first_seen)) m FROM items WHERE source = ?",
        (source,),
    )
    row = cur.fetchone()
    return row["m"] if row else None


# --- story clustering -------------------------------------------------------

def recent_cluster_rows(conn, since_iso):
    """Rows used to attach new items to an existing story cluster."""
    return conn.execute(
        "SELECT title, title_key, cluster_id, source FROM items WHERE first_seen >= ?",
        (since_iso,),
    ).fetchall()


def _rung_rank(label):
    try:
        return config.LIKELIHOOD_RUNGS.index(label)
    except (ValueError, AttributeError):
        return -1


def _is_fresh(row):
    """Drop stale items: perishable match content past a tight cap, and anything
    older than its category's shelf life."""
    from datetime import datetime, timezone
    ts = row["published_at"] or row["first_seen"]
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if config.is_perishable(row["title"]) and age_h > config.PERISHABLE_MAX_HOURS:
        return False
    max_days = config.CATEGORY_MAX_AGE_DAYS.get(row["category"], 999)
    return age_h <= max_days * 24


def query_clusters(conn, page="arsenal", category=None, source=None, search=None,
                   club=None, min_rung=None, limit=300):
    """Return collapsed stories. Each cluster = one representative item plus
    aggregated source consensus, best likelihood rung, and insider flag."""
    if page and page != "all":
        sql = "SELECT * FROM items WHERE page = ?"
        params = [page]
    else:
        sql = "SELECT * FROM items WHERE 1=1"
        params = []
    if category and category != "All":
        sql += " AND category = ?"
        params.append(category)
    if source and source != "All":
        sql += " AND source = ?"
        params.append(source)
    if club and club != "All":
        sql += " AND clubs LIKE ?"
        params.append(f"%{club}%")
    if search:
        sql += " AND (title LIKE ? OR summary LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY COALESCE(published_at, first_seen) DESC LIMIT 1500"
    rows = conn.execute(sql, params).fetchall()
    rows = [r for r in rows if _is_fresh(r)]

    clusters = {}
    order = []
    for r in rows:
        cid = r["cluster_id"] or r["url_hash"]
        if cid not in clusters:
            clusters[cid] = {
                "rep": r,
                "sources": set(),
                "best_rung": -1,
                "best_likelihood": r["likelihood"],
                "has_insider": False,
                "members": [],
            }
            order.append(cid)
        c = clusters[cid]
        c["members"].append(r)
        if r["source"]:
            c["sources"].add(r["source"])
        if r["credibility"] == "insider":
            c["has_insider"] = True
        rr = _rung_rank(r["likelihood"])
        if rr > c["best_rung"]:
            c["best_rung"] = rr
            c["best_likelihood"] = r["likelihood"]
        # representative = highest credibility, then most recent (rows already desc)
        cred_order = {"insider": 3, "high": 2, "medium": 1, "low": 0}
        if cred_order.get(r["credibility"], 0) > cred_order.get(c["rep"]["credibility"], 0):
            c["rep"] = r

    out = []
    for cid in order:
        c = clusters[cid]
        if min_rung and _rung_rank(c["best_likelihood"]) < _rung_rank(min_rung):
            continue
        rep = dict(c["rep"])
        rep["source_count"] = len(c["sources"])
        rep["sources_list"] = sorted(c["sources"])
        rep["best_likelihood"] = c["best_likelihood"]
        rep["has_insider"] = c["has_insider"]
        rep["member_count"] = len(c["members"])
        out.append(rep)
        if len(out) >= limit:
            break
    return out


# --- derived views ----------------------------------------------------------

def heat_leaderboard(conn, page="arsenal", limit=8, days=14):
    """Players ranked by mentions x average likelihood (transfer chatter)."""
    cutoff = _days_ago(days)
    page_clause = "" if page in (None, "all") else "page = ? AND "
    params = ([] if page in (None, "all") else [page]) + [cutoff]
    rows = conn.execute(
        f"""SELECT player, title, likelihood, COALESCE(published_at, first_seen) ts
           FROM items
           WHERE {page_clause} category = 'Transfers' AND player IS NOT NULL
                 AND player <> '' AND COALESCE(published_at, first_seen) >= ?""",
        params,
    ).fetchall()
    arsenal_focus = (page == "arsenal")
    agg = {}
    for r in rows:
        # Arsenal heat = Arsenal's own men's first-team incoming targets only
        if arsenal_focus:
            if not config.mentions_arsenal(r["title"]):
                continue
            if config.exclude_from_arsenal_heat(r["title"]):
                continue
        elif config.is_womens(r["title"]):
            continue
        p = r["player"]
        a = agg.setdefault(p, {"mentions": 0, "rung_sum": 0, "best": -1, "best_label": "Rumour"})
        a["mentions"] += 1
        rr = _rung_rank(r["likelihood"])
        a["rung_sum"] += max(rr, 0)
        if rr > a["best"]:
            a["best"] = rr
            a["best_label"] = r["likelihood"]
    board = []
    for p, a in agg.items():
        avg = a["rung_sum"] / a["mentions"] if a["mentions"] else 0
        # heat score: mentions weighted, nudged by average rung
        score = a["mentions"] * (1 + avg / 3)
        board.append({"player": p, "mentions": a["mentions"], "heat": round(score, 1),
                      "best_likelihood": a["best_label"]})
    board.sort(key=lambda x: x["heat"], reverse=True)
    return board[:limit]


def heat_page(conn, page="arsenal", days=14):
    """Full rumour-heat board with momentum + latest report per player.

    Same filtering as heat_leaderboard so the widget and the /heat page agree,
    but returns every player (no top-8 cut) plus richer per-player detail:
    latest headline/url/source/club, last-updated ts, and a momentum signal
    (mentions in the last 3 days vs the 3 before that)."""
    cutoff = _days_ago(days)
    recent_cut = _days_ago(3)
    prev_cut = _days_ago(6)
    new_cut = _days_ago(2)
    page_clause = "" if page in (None, "all") else "page = ? AND "
    params = ([] if page in (None, "all") else [page]) + [cutoff]
    rows = conn.execute(
        f"""SELECT player, title, url, source, clubs, likelihood,
                  COALESCE(published_at, first_seen) ts
           FROM items
           WHERE {page_clause} category = 'Transfers' AND player IS NOT NULL
                 AND player <> '' AND COALESCE(published_at, first_seen) >= ?
           ORDER BY ts ASC""",
        params,
    ).fetchall()
    arsenal_focus = (page == "arsenal")
    agg = {}
    for r in rows:
        if arsenal_focus:
            if not config.mentions_arsenal(r["title"]):
                continue
            if config.exclude_from_arsenal_heat(r["title"]):
                continue
        elif config.is_womens(r["title"]):
            continue
        p = r["player"]
        a = agg.setdefault(p, {"mentions": 0, "rung_sum": 0, "best": -1,
                               "best_label": "Rumour", "recent": 0, "prev": 0,
                               "first_ts": r["ts"], "latest": None})
        a["mentions"] += 1
        rr = _rung_rank(r["likelihood"])
        a["rung_sum"] += max(rr, 0)
        if rr > a["best"]:
            a["best"] = rr
            a["best_label"] = r["likelihood"]
        ts = r["ts"] or ""
        if ts >= recent_cut:
            a["recent"] += 1
        elif ts >= prev_cut:
            a["prev"] += 1
        # rows are oldest-first, so the last write wins as "latest"
        a["latest"] = {"title": r["title"], "url": r["url"], "source": r["source"],
                       "club": (r["clubs"] or "").split(",")[0].strip(), "ts": ts}
    board = []
    for p, a in agg.items():
        avg = a["rung_sum"] / a["mentions"] if a["mentions"] else 0
        score = a["mentions"] * (1 + avg / 3)
        if a["recent"] > a["prev"]:
            momentum = "rising"
        elif a["recent"] < a["prev"]:
            momentum = "cooling"
        else:
            momentum = "steady"
        latest = a["latest"] or {}
        board.append({
            "player": p,
            "mentions": a["mentions"],
            "heat": round(score, 1),
            "best_likelihood": a["best_label"],
            "momentum": momentum,
            "is_new": a["first_ts"] >= new_cut,
            "last_ts": latest.get("ts", ""),
            "latest_title": latest.get("title", ""),
            "latest_url": latest.get("url", ""),
            "latest_source": latest.get("source", ""),
            "club": latest.get("club", ""),
        })
    board.sort(key=lambda x: x["heat"], reverse=True)
    return board


def injury_board(conn, limit=12, days=30):
    cutoff = _days_ago(days)
    return conn.execute(
        """SELECT title, url, source, player, COALESCE(published_at, first_seen) ts
           FROM items
           WHERE page = 'arsenal' AND category = 'Injuries'
                 AND COALESCE(published_at, first_seen) >= ?
           ORDER BY ts DESC LIMIT ?""",
        (cutoff, limit),
    ).fetchall()


def done_deals(conn, page="arsenal", limit=12, days=45):
    cutoff = _days_ago(days)
    page_clause = "" if page in (None, "all") else "page = ? AND "
    params = ([] if page in (None, "all") else [page]) + [cutoff]
    rows = conn.execute(
        f"""SELECT title, url, source, player, clubs, COALESCE(published_at, first_seen) ts
           FROM items
           WHERE {page_clause} category = 'Transfers' AND likelihood = 'Here we go'
                 AND player IS NOT NULL AND player <> ''
                 AND COALESCE(published_at, first_seen) >= ?
           ORDER BY ts DESC""",
        params,
    ).fetchall()
    # On the Arsenal tab, only show Arsenal's own confirmed deals
    if page == "arsenal":
        rows = [r for r in rows if config.mentions_arsenal(r["title"])
                and not config.is_womens(r["title"])]
    return rows[:limit]


def saga(conn, player, page="arsenal"):
    """All transfer items for a player, oldest first, to show momentum."""
    return conn.execute(
        """SELECT title, url, source, credibility, likelihood,
                  COALESCE(published_at, first_seen) ts
           FROM items
           WHERE page = ? AND category = 'Transfers' AND player = ?
           ORDER BY ts ASC""",
        (page, player),
    ).fetchall()


def distinct_players(conn, page="arsenal", days=21):
    cutoff = _days_ago(days)
    rows = conn.execute(
        """SELECT player, COUNT(*) n FROM items
           WHERE page = ? AND category='Transfers' AND player IS NOT NULL AND player <> ''
                 AND COALESCE(published_at, first_seen) >= ?
           GROUP BY player ORDER BY n DESC""",
        (page, cutoff),
    ).fetchall()
    return [r["player"] for r in rows]


def _days_ago(days):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# --- kv cache + alerts ------------------------------------------------------

def kv_get(conn, key):
    row = conn.execute("SELECT value, updated_at FROM kv_cache WHERE key = ?", (key,)).fetchone()
    return row


def kv_set(conn, key, value, updated_at):
    conn.execute(
        """INSERT INTO kv_cache (key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, value, updated_at),
    )


def not_yet_alerted(conn, url_hash):
    return conn.execute(
        "SELECT 1 FROM alerts_sent WHERE url_hash = ?", (url_hash,)
    ).fetchone() is None


def mark_alerted(conn, url_hash, sent_at):
    conn.execute(
        "INSERT OR IGNORE INTO alerts_sent (url_hash, sent_at) VALUES (?, ?)",
        (url_hash, sent_at),
    )


def last_scrape_time(conn):
    cur = conn.execute("SELECT MAX(last_run) m FROM feed_state")
    row = cur.fetchone()
    return row["m"] if row else None


def feed_health(conn):
    cur = conn.execute(
        "SELECT source, fail_count, last_run, last_status FROM feed_state ORDER BY source"
    )
    return cur.fetchall()


if __name__ == "__main__":
    init_db()
    print(f"Initialised DB at {config.DB_PATH}")
