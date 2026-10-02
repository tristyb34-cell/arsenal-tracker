# Arsenal Tracker

A personal localhost newsroom for everything Arsenal plus a Europe-wide transfer
desk. Scrapes a tiered set of verified feeds 4x a day and serves a filterable
two-page dashboard at **http://127.0.0.1:5057**.

## Screens

One app, served two ways (see "One UI, two front doors" below). Bottom tab bar on
a phone, top nav on desktop:

- **Home** (`#/`): the match first. A scoreboard card for the next fixture (kick-off
  in SAST, countdown) that becomes a live score card with a ticking minute on
  matchday and a result card for 30 hours afterwards. Then recent results, the
  Premier League around Arsenal, top stories, injuries and team news.
- **Matches** (`#/matches`): every Arsenal game in every competition, upcoming and
  results, competition chips, grouped by month. Every row opens the match centre.
- **Match centre** (`#/match/<id>`): scoreboard with scorers and the match rail
  (90 minutes as a line, goals where they happened), then tabs: Timeline (goals,
  cards, subs; newest first while live), Line-ups (formation pitch, kit colours,
  goal/card badges, sub minutes, bench), Stats (possession, shots, on target,
  corners, fouls, offsides, cards, saves) and Preview / Team news before kick-off.
- **News** (`#/news`, `#/news/others`, `#/news/all`, `#/heat`, `#/saga/<player>`): the
  Arsenal feed, other clubs' transfer desk, everything combined, rumour heat and
  per-player sagas.
- **Table** (`#/table`): Premier League, plus the Champions League league phase.

Design rules live in `DESIGN.md`.

## Football data (ESPN, free, no key)

- `fixtures.py` reads Arsenal's whole season in two calls:
  `soccer/all/teams/359/schedule` (results) and `...?fixture=true` (upcoming).
  Friendlies are filtered out. Until 2026-10-02 it sliced per-competition
  scoreboards by date range; ESPN started answering any `dates=A-B` range with
  HTTP 400, the error was swallowed, and the fixtures list was empty from 16 Sep
  while the log said "football refreshed". It now raises instead, keeps the last
  good cache, and the scrape log prints result and fixture counts.
- `matchcentre.py` shapes ESPN's match summary: status and clock, scorers (pens and
  own goals marked; `keyEvents.team` is the side that benefited), the timeline,
  team stats, line-ups with kit colours and per-player badges. Cached per match in
  `kv_cache` (`SCHEMA` busts old shapes).
- `export.py` writes `docs/data/snapshot.json`, one `docs/data/match/<id>.json` per
  result plus the live and next match, and `docs/data/sagas.json`. While a match
  is in its window it patches the live score and clock into the fixtures block.
- During a match the phone also polls ESPN's summary itself every 30 seconds
  (ESPN allows cross-origin requests) and ticks the minute between polls, because
  the published snapshot only moves every 30 minutes. `parseSummary()` in
  `docs/app.js` mirrors `matchcentre.py`.
- `live_alerts.py` (launchd, every minute) sends Telegram alerts for the XI,
  kick-off, goals, red cards, HT and FT.

## One UI, two front doors

`docs/` (`index.html`, `app.js`, `style.css`, `sw.js`) is the only UI. GitHub Pages
serves it with the pushed static data; Flask (`app.py`, 127.0.0.1:5057) serves the
same files and builds the JSON live from `arsenal.db`, plus a Refresh button
(`POST /refresh` runs a scrape). Old desktop URLs (`/fixtures`, `/match/<id>`,
`/europe`, `/all`, `/heat`, `/saga/<p>`) redirect to the matching screen. The Jinja
templates were removed on 2026-10-02 so the desktop and phone can no longer drift.

## v3 intelligence layer

- **Story clustering** — cross-source reports of the same story are linked; the
  card shows "N sources" (consensus = credibility).
- **Player extraction** (`enrich.py`) — claude names the player in each transfer
  item, powering sagas, the heat leaderboard, and the deals ledger.
- **Football** (`fixtures.py`, `matchcentre.py`): every Arsenal match in every
  competition, match centres, PL and UCL tables via ESPN's free API.
- **Morning brief** (`brief.py`) — claude writes a short daily summary, cached.
- **Native alerts** (`alerts.py`) — macOS notification on a confirmed "Here we
  go" or an insider Arsenal post (deduped, fires once per item).
- **PWA** — installable on a phone home screen (manifest + service worker +
  icons), bottom tab nav, 5-minute auto-refresh.
- **Matchday skin** — the UI lights up red on matchday (`is_matchday`). A
  deadline-day mode can reuse the same styling (not yet date-triggered).

## Phone install (static PWA on GitHub Pages)

The desktop app stays a localhost Flask app. For the phone, the Mac also publishes
a **static client-rendered clone** to GitHub Pages, so it installs as a real PWA
and works anywhere (no tunnel, no always-on requirement beyond the Mac scraping).

```
arsenal.db  ->  export.py  ->  docs/data/snapshot.json  --git push-->  GitHub Pages  ->  phone PWA
```

- **export.py** dumps the DB (via the same `db.py` queries) to one
  `docs/data/snapshot.json` (~712 KB, ~177 KB gzipped).
- **docs/** is a static SPA (`index.html` + `app.js` + `style.css`) that fetches
  that JSON and renders every screen client-side. Hash routing so refresh never
  404s.
- **docs/sw.js** is network-first for the data (always fresh online, cached
  fallback offline) and cache-first for the app shell.
- **run_scrape.sh** runs `export.py` and `git push`es the fresh snapshot after
  every scrape, so the live site updates 4x/day automatically.
- Live: **https://tristyb34-cell.github.io/arsenal-tracker/** — open on the phone,
  Share → Add to Home Screen.

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
highest tier whose patterns match the headline. Insider sources (Fabrizio
Romano, David Ornstein) boost the rung one notch (capped at Advanced unless the
language itself already says "here we go"). Tune the patterns in `config.py`
(`LIKELIHOOD_PATTERNS`).

Matching is **word-boundary regex with slack for intervening words** (`GAP`), not
substring matching. Real headlines interleave words ("agree £150k deal"), inflect
verbs ("complete" vs "completed") and wrap claims in quotes ('deal "done"'). The
original substring engine matched none of those, so 62% of all transfer items
fell through to the Rumour default and the ladder was decorative. Guards:

- a "done" claim wrapped in future language ("set to complete", "nears
  completion", a question mark) is capped at Advanced,
- **except** when the headline literally says "here we go" (Romano's sign-off),
- a bid that is only *planned* or *prepared* is Developing, not Advanced.

`test_likelihood.py` holds hand-labelled real headlines for all of this. Run it
after touching the patterns: `./venv/bin/python -m pytest test_likelihood.py -q`.

## What earns the Arsenal tab

The Arsenal tab is Arsenal news only, and the signal is read from the **title**,
never the summary. A BBC gossip round-up names ten clubs in its summary, which is
how "Man City brace for Rodri bid" used to appear on the Arsenal tab.

A **transfer** reaches the Arsenal tab when the headline:

1. names the club (`ARSENAL_STRONG_TERMS`), or
2. names one of our players (`ARSENAL_SQUAD_TERMS`), or
3. names a player in the **orbit** and no other club.

The orbit (`db.arsenal_orbit_players`) is derived from transfer headlines that
explicitly name Arsenal, so it learns each window's targets instead of relying on
a hand-maintained list. That is what lets "Bruno Guimaraes deal done" through
without opening the tab to every player alive. The "no other club" guard is what
keeps "Atletico CEO on Alvarez and Barcelona" out: an orbit player, but not an
Arsenal story. `OTHER_CLUB_TERMS` exists purely for that veto, because only 19
clubs are tracked for display and "Fenerbahce ready huge Rashford offer" would
otherwise look club-less.

Ambiguous bare surnames used to be in the Arsenal term list ("white", "rice",
"timber", "jesus", "gabriel"), which tagged "Jesus Navas retires" and "Timber
merchant strikes gold" as Arsenal. Those now require the full name.

**Women's football is excluded entirely**, dropped at ingest rather than hidden.
Headlines often never say "women", so `WOMENS_CLUB_TERMS` (NWSL/WSL clubs) and
`WOMENS_PLAYER_TERMS` do the work: "Jenna Nighswonger to join Bay FC" has no
other tell.

## Story clustering

Cross-source variants of one story share a `cluster_id`, and the card shows
"N sources". Scoring is word **overlap** on *story* words: the player name and
every club name are stripped first, because they are constant across a saga.

Getting this wrong is actively misleading, not just untidy. The card displays the
cluster's highest rung, so when clustering merged an entire Vinicius saga into
one cluster, a card reading "Could Vinicius Jr really be heading to Arsenal?"
displayed **HERE WE GO**. Thresholds live in `config.py`
(`CLUSTER_THRESHOLD`, `CLUSTER_THRESHOLD_NO_PLAYER`, `CLUSTER_MIN_SHARED`).
Prefer under-clustering: a cluster of one is honest, a false merge is not.

Player names are canonicalised on write (`config.canonical_player`), so
"Vinicius Jr" and "Vinícius Júnior" are one player on the heat board and saga
pages rather than three.

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

- `com.arsenal.tracker.scrape` — runs `run_scrape.sh` every 30 minutes (`StartInterval`)
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
| `app.py` | Flask: serves `docs/` plus live JSON |
| `fixtures.py` | ESPN schedule, results, tables |
| `matchcentre.py` | ESPN match summary shaping (scorers, timeline, stats, line-ups) |
| `export.py` | Writes `docs/data/` for Pages |
| `live_alerts.py` | Telegram match alerts |
| `probe_feeds.py` | Empirical feed health checker |
| `docs/` | The app (HTML, JS, CSS, service worker, data) |
| `arsenal.db` | The data (created on first run) |
| `logs/` | scrape + launchd logs |

## Tuning

- **Add/remove a source:** edit `SOURCES` in `config.py` (set `arsenal_specific`
  False for general feeds so the relevance filter applies).
- **Adjust categories:** edit `CATEGORIES` keyword lists in `config.py`. They are
  matched on word boundaries and title hits count double (`TITLE_WEIGHT`).
- **Change schedule:** edit `StartInterval` in the scrape plist. It was four fixed
  times (08/11/14/17), which left a 15-hour blackout from 17:00 to 08:00 and an
  average 5.6-hour lag from publication to appearing. `StartInterval` also fires
  on wake, so a sleeping Mac catches up immediately.
- **Change port:** edit `PORT` in `config.py`.
