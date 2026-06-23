# Arsenal Tracker

A personal localhost newsroom for everything Arsenal plus a Europe-wide transfer
desk. Scrapes a tiered set of verified feeds 4x a day and serves a filterable
two-page dashboard at **http://127.0.0.1:5057**.

## Pages

- **Arsenal** (`/`) — Broadcast Dark command centre: top-story hero, morning
  brief, clustered feed with segmented likelihood meters and source-consensus,
  plus a right rail (PL table, rumour heat, done deals, injury room) and a live
  football strip (next match / last result / form / table).
- **Europe / Other Clubs** (`/europe`) — transfer desk: a club crest wall, then
  transfers grouped by club, each with its likelihood rung.
- **Saga** (`/saga/<player>`) — per-player transfer timeline showing the
  likelihood climbing (or stalling) over time.

## v3 intelligence layer

- **Story clustering** — cross-source reports of the same story are linked; the
  card shows "N sources" (consensus = credibility).
- **Player extraction** (`enrich.py`) — claude names the player in each transfer
  item, powering sagas, the heat leaderboard, and the deals ledger.
- **Football** (`fixtures.py`) — Arsenal fixtures/results/form + PL table via
  ESPN's free API. Degrades gracefully in the off-season.
- **Morning brief** (`brief.py`) — claude writes a short daily summary, cached.
- **Native alerts** (`alerts.py`) — macOS notification on a confirmed "Here we
  go" or an insider Arsenal post (deduped, fires once per item).
- **PWA** — installable on a phone home screen (manifest + service worker +
  icons), bottom tab nav, 5-minute auto-refresh, confetti on "here we go".
- **Matchday skin** — the UI lights up red on matchday (`is_matchday`). A
  deadline-day mode can reuse the same styling (not yet date-triggered).

## How it works

```
feeds (RSS / X mirrors)  ->  scrape.py  ->  arsenal.db (SQLite)  ->  app.py (Flask)  ->  localhost:5057
```

- **scrape.py** fetches every source with conditional GET (ETag/Last-Modified),
  polite User-Agent, random delays, per-source backoff. It tags each item to
  tracked clubs, dedupes by URL + fuzzy title, categorises, scores transfer
  likelihood, then routes to the Arsenal or Europe page.
- **categorise.py** buckets items into Transfers / Injuries / Match & Results /
  General using keyword rules, with the `claude` CLI as a fallback for ambiguous
  headlines (free, no API key).
- **config.py** holds the likelihood ladder and club tagging logic.
- **app.py** serves both pages: tabs, filters, search, manual "Refresh", feed health.

## Likelihood ladder (transfer items)

Low → high: **Rumour → Developing → Advanced → Here we go**. An item's rung is the
highest tier whose keywords appear in the headline. Insider sources (Fabrizio
Romano, David Ornstein) boost the rung one notch (capped at Advanced unless the
language itself already says "here we go"). Tune the keyword lists in
`config.py` (`LIKELIHOOD_KEYWORDS`).

## Tracked clubs (Europe page)

Prem: Man City, Man Utd, Liverpool, Chelsea, Tottenham, Aston Villa, Newcastle,
Everton. Europe: Barcelona, Real Madrid, Atlético, Dortmund, Bayern, Juventus,
Inter, AC Milan, PSG, Napoli. Tagging terms live in `config.py` (`CLUB_TERMS`).

## Sources (verified live)

Three tiers so we're never dependent on one fragile feed. Run
`./venv/bin/python probe_feeds.py` anytime to re-check feed health and prune/swap
dead URLs in `config.py`.

- **Tier 1 (solid RSS):** BBC Sport, The Guardian, football.london, Arseblog News,
  Caught Offside, Daily Cannon
- **Tier 2 (dedicated Arsenal blogs):** Sport Witness, Pain in the Arsenal, Just Arsenal
- **Tier 3 (X insiders via nitter mirror, best-effort):** Fabrizio Romano, David Ornstein

**Broad transfer feeds (Europe page):** BBC Gossip, Guardian Transfer Window,
Sky Transfer Centre, Football Italia (Serie A), plus the two insiders above.

> Note: David Ornstein's primary outlet (The Athletic) is paywalled with no clean
> RSS, so we read his X feed via mirror. If the mirror dies, Tier 1/2 still catch
> the same stories. Sky Sports and Arsenal.com official were dropped (no clean
> Arsenal-only feed / dead RSS respectively).

## Schedule

Two launchd agents (in `~/Library/LaunchAgents/`):

- `com.arsenal.tracker.scrape` — runs `run_scrape.sh` at 08:00, 11:00, 14:00, 17:00
- `com.arsenal.tracker.app` — keeps the dashboard alive (RunAtLoad + KeepAlive)

```bash
# reload after editing a plist
launchctl unload ~/Library/LaunchAgents/com.arsenal.tracker.scrape.plist
launchctl load   ~/Library/LaunchAgents/com.arsenal.tracker.scrape.plist

# run a scrape right now
./venv/bin/python scrape.py

# check agent state
launchctl list | grep arsenal
```

## Files

| File | Purpose |
|------|---------|
| `config.py` | Sources, tiers, relevance filter, category keywords, settings |
| `db.py` | SQLite schema + queries |
| `scrape.py` | Fetch + filter + dedupe + categorise + store |
| `categorise.py` | Keyword rules + claude CLI fallback |
| `app.py` | Flask dashboard |
| `probe_feeds.py` | Empirical feed health checker |
| `templates/index.html`, `static/style.css` | Dashboard UI |
| `arsenal.db` | The data (created on first run) |
| `logs/` | scrape + launchd logs |

## Tuning

- **Add/remove a source:** edit `SOURCES` in `config.py` (set `arsenal_specific`
  False for general feeds so the relevance filter applies).
- **Adjust categories:** edit `CATEGORIES` keyword lists in `config.py`.
- **Change schedule:** edit the `StartCalendarInterval` block in the scrape plist.
- **Change port:** edit `PORT` in `config.py`.
