#!/bin/bash
# Arsenal Tracker scrape wrapper (called by launchd 4x/day, 8am-5pm).
# launchd uses a minimal PATH; add ~/.local/bin so the claude CLI is found.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")" || exit 1
echo "----- $(date) -----" >> logs/scrape.log
./venv/bin/python scrape.py >> logs/scrape.log 2>&1
