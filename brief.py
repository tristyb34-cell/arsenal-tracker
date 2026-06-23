"""AI morning briefing: a short, conversational summary of the day's top Arsenal
items, written by the `claude` CLI (free, no API key). Cached daily in kv_cache.
"""

import json
from datetime import datetime, timedelta, timezone

import config
import db


def _top_items(conn, hours=18, limit=14):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        """SELECT title, category, likelihood, source, player
           FROM items
           WHERE page = 'arsenal' AND COALESCE(published_at, first_seen) >= ?
           ORDER BY
             CASE credibility WHEN 'insider' THEN 0 WHEN 'high' THEN 1
                              WHEN 'medium' THEN 2 ELSE 3 END,
             COALESCE(published_at, first_seen) DESC
           LIMIT 40""",
        (cutoff,),
    ).fetchall()
    # drop perishable match previews/lineups so the brief never leads with a
    # "expected to start" that has already happened
    fresh = [r for r in rows if not config.is_perishable(r["title"])]
    return fresh[:limit]


def _compose_prompt(rows):
    lines = []
    for r in rows:
        bits = [r["title"]]
        meta = []
        if r["category"]:
            meta.append(r["category"])
        if r["likelihood"]:
            meta.append(r["likelihood"])
        if r["source"]:
            meta.append(r["source"])
        lines.append(f"- {r['title']} ({', '.join(meta)})")
    headlines = "\n".join(lines)
    return (
        "You are writing a short morning briefing for an Arsenal supporter, in the "
        "voice of a sharp, friendly football pundit. Summarise the day's Arsenal "
        "news below into 3 to 4 punchy sentences. Lead with the biggest story. "
        "Be honest about how solid each rumour is (a 'Rumour' is speculative, a "
        "'Here we go' is basically done). Do not use bullet points, headers, or "
        "em dashes. Just the briefing text.\n\n"
        f"Today's Arsenal items:\n{headlines}"
    )


def generate(conn):
    rows = _top_items(conn)
    if not rows:
        text = "Quiet on the Arsenal front right now. No fresh stories in the last day. Check back after the next scrape."
    else:
        import subprocess
        try:
            proc = subprocess.run(
                [config.CLAUDE_BIN, "-p", _compose_prompt(rows)],
                capture_output=True, text=True, timeout=150,
            )
            text = proc.stdout.strip() or "Could not generate a briefing this time."
            text = text.replace("—", ", ").replace(" – ", ", ")
        except Exception:
            text = "Briefing unavailable (generator error). The feed below is still live."

    payload = {"text": text, "generated_at": datetime.now(timezone.utc).isoformat(),
               "item_count": len(rows)}
    db.kv_set(conn, "brief", json.dumps(payload), payload["generated_at"])
    return payload


def get_cached(conn):
    row = db.kv_get(conn, "brief")
    if not row or not row["value"]:
        return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return None


def refresh_if_stale(conn, max_age_hours=4):
    """Regenerate the brief if there isn't a fresh one."""
    cached = get_cached(conn)
    if cached:
        try:
            gen = datetime.fromisoformat(cached["generated_at"])
            if datetime.now(timezone.utc) - gen < timedelta(hours=max_age_hours):
                return cached
        except (ValueError, KeyError):
            pass
    return generate(conn)
