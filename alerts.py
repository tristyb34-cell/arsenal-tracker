"""Native macOS notifications for big Arsenal moments.

Fires once per item (deduped via the alerts_sent table) when:
  - a confirmed 'Here we go' Arsenal transfer lands, or
  - an insider (Romano / Ornstein) posts Arsenal news.
"""

import subprocess
from datetime import datetime, timezone

import db


def _notify(title, message, subtitle=""):
    # keep strings safe for AppleScript (escape double quotes)
    def esc(s):
        return (s or "").replace('"', '\\"')
    script = (
        f'display notification "{esc(message)}" '
        f'with title "{esc(title)}"'
    )
    if subtitle:
        script += f' subtitle "{esc(subtitle)}"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def process(conn, stored_items):
    """Given the items just stored this cycle, fire alerts for the notable ones."""
    fired = 0
    now = datetime.now(timezone.utc).isoformat()
    for it in stored_items:
        if it.get("page") != "arsenal":
            continue
        is_here_we_go = (it.get("category") == "Transfers"
                         and it.get("likelihood") == "Here we go")
        is_insider = it.get("credibility") == "insider"
        if not (is_here_we_go or is_insider):
            continue
        if not db.not_yet_alerted(conn, it["url_hash"]):
            continue

        if is_here_we_go:
            title = "🚨 Arsenal: Here we go!"
            sub = it.get("player") or "Transfer confirmed"
        else:
            title = "🔵 Arsenal insider"
            sub = it["source"]
        _notify(title, it["title"][:180], sub)
        db.mark_alerted(conn, it["url_hash"], now)
        fired += 1
    return fired
