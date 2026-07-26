#!/bin/bash
# Arsenal Tracker scrape wrapper (called by launchd 4x/day, 8am-5pm).
# launchd uses a minimal PATH. ~/.local/bin has the claude CLI; /opt/homebrew/bin
# has gitleaks, which the pre-commit hook execs — without it the hook exits 127,
# the commit aborts, and the phone PWA silently freezes (it did, for a month).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")" || exit 1
echo "----- $(date) -----" >> logs/scrape.log
./venv/bin/python scrape.py >> logs/scrape.log 2>&1

# Export the static snapshot and publish to GitHub Pages (powers the phone PWA).
# The Mac stays the source of truth; this just pushes a fresh docs/data/snapshot.json.
./venv/bin/python export.py >> logs/scrape.log 2>&1
# Each step is checked. The old version pushed regardless of whether the commit
# succeeded, and `git push` on an unchanged branch exits 0 — so a failing commit
# logged "published snapshot to Pages" every run while publishing nothing.
if ! git diff --quiet -- docs/data/snapshot.json 2>/dev/null; then
  git add docs/data/snapshot.json
  if ! git commit -q -m "Update snapshot $(date -u +%Y-%m-%dT%H:%MZ)" >> logs/scrape.log 2>&1; then
    echo "snapshot COMMIT FAILED (pre-commit hook? see above) — Pages not updated" >> logs/scrape.log
  elif GIT_TERMINAL_PROMPT=0 git push -q origin main >> logs/scrape.log 2>&1; then
    echo "published snapshot to Pages" >> logs/scrape.log
  else
    echo "snapshot PUSH FAILED (check git auth) — Pages not updated" >> logs/scrape.log
  fi
fi

# Freshness guard: if what GitHub Pages serves is more than a day behind the
# local database, the phone app is stale no matter what the steps above said.
./venv/bin/python - >> logs/scrape.log 2>&1 <<'PY'
import json, subprocess, urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://tristyb34-cell.github.io/arsenal-tracker/data/snapshot.json"
try:
    with urllib.request.urlopen(URL, timeout=30) as r:
        live = json.load(r).get("generated_at")
    age = datetime.now(timezone.utc) - datetime.fromisoformat(live)
    if age > timedelta(days=1):
        msg = f"PHONE APP STALE: Pages snapshot is {age.days}d old ({live})"
        print(msg)
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "Arsenal Tracker"'], check=False)
    else:
        print(f"Pages snapshot fresh ({live})")
except Exception as e:
    print(f"freshness check skipped: {e}")
PY
