#!/bin/bash
# Arsenal Tracker scrape wrapper (called by launchd 4x/day, 8am-5pm).
# launchd uses a minimal PATH; add ~/.local/bin so the claude CLI is found.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")" || exit 1
echo "----- $(date) -----" >> logs/scrape.log
./venv/bin/python scrape.py >> logs/scrape.log 2>&1

# Export the static snapshot and publish to GitHub Pages (powers the phone PWA).
# The Mac stays the source of truth; this just pushes a fresh docs/data/snapshot.json.
./venv/bin/python export.py >> logs/scrape.log 2>&1
if ! git diff --quiet -- docs/data/snapshot.json 2>/dev/null; then
  git add docs/data/snapshot.json
  git commit -q -m "Update snapshot $(date -u +%Y-%m-%dT%H:%MZ)" >> logs/scrape.log 2>&1
  GIT_TERMINAL_PROMPT=0 git push -q origin main >> logs/scrape.log 2>&1 \
    && echo "published snapshot to Pages" >> logs/scrape.log 2>&1 \
    || echo "snapshot push FAILED (check git auth)" >> logs/scrape.log 2>&1
fi
