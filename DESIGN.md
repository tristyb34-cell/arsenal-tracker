# Arsenal Tracker: Design System Contract

The persistent design contract for the Arsenal Tracker app. Read it before touching `docs/style.css` or `docs/app.js`. Rewritten on 2026-10-02 for the club-app rebuild (Home / Matches / match centre / News / Table). Every value here is **real**: it is what the stylesheet ships today.

---

## 1. Purpose & personality

A personal Arsenal club app, read on an iPhone first. The bar is FotMob and the official Arsenal app: the match leads, news supports.

- **Who:** one Arsenal fan in Johannesburg. Opens it to answer "when's the next game / what's the score / what happened", then reads the news.
- **Feel:** a broadcast gallery at night. Dark navy surfaces, Arsenal red as the signal, scores set like a scoreboard.
- **Principles:**
  - The match is the hero. Every match surface uses the same scoreboard grammar (crest, score or kick-off, crest).
  - Red means "Arsenal, now": live, the active tab, Arsenal's own row. Never a fill for decoration.
  - Structure carries meaning. No eyebrow labels, no explainer paragraphs, no middle-dot strings: layout separates the facts.
  - One signature, used consistently: the **match rail** (section 6).

---

## 2. Tech stack and the one-UI rule

- **One client** in `docs/` (`index.html`, `app.js`, `style.css`, `sw.js`), plain JavaScript, plain CSS, no framework, no build step.
- **Two front doors, same files.** GitHub Pages serves `docs/` with a static `data/snapshot.json` pushed after every scrape. Flask (`app.py`, `127.0.0.1:5057`) serves the same `docs/` files and builds the same JSON live from `arsenal.db`. The Jinja templates were deleted on 2026-10-02 because the desktop and phone UIs drifted every time one was touched. **Never reintroduce a second UI.** Desktop-only behaviour is CSS (`min-width:900px`) or a flag in the JSON (`local: true` unlocks the Refresh button).
- **Data files:** `data/snapshot.json` (everything Home/Matches/News/Table need), `data/match/<id>.json` (one match centre per finished, live and next match), `data/sagas.json` (loaded only on a saga page; it was ~460 KB of a 1 MB snapshot).
- **Live:** during a match the client polls ESPN's summary directly every 30s (ESPN sends `access-control-allow-origin: *`). `parseSummary()` in `app.js` mirrors `matchcentre.py`; change one, change the other.
- **Design tokens are CSS custom properties on `:root`.** Any colour used twice is a token.

---

## 3. Colour

### Surfaces (one navy hue, lightness climbs)
| Token | Value | Role |
|---|---|---|
| `--bg` | `#0a0e16` | Page. Also input wells (inputs sit darker than their card). |
| `--bg2` | `#121826` | Cards and grouped lists. |
| `--bg3` | `#1a2233` | Raised: minute pills, chips' pressed state, empty meter segments. |
| `--bg4` | `#222b3e` | Selected segment, HT/FT markers, the "All" crest tile. |
| `--line` | `#232c40` | Solid borders (chips, inputs). |
| `--line-soft` | `rgba(255,255,255,.06)` | Card edges and row dividers. Borders should disappear until you look for them. |
| `--line-strong` | `rgba(255,255,255,.16)` | Hover/selected edges, the HT tick on the rail. |

### Text (four levels)
`--text #e7ecf3` (primary), `--grey-text #c5cddb` (strong secondary: scorer names, headlines under a heading), `--muted #8b97ad` (secondary, 6.0:1 on `--bg2`), `--dim #7a8aa3` (metadata only, 5.1:1 on `--bg2`, 4.5:1 on `--bg3`: never smaller than .72rem on `--bg3`).

### Signal colours, one meaning each
| Token | Meaning |
|---|---|
| `--red #ef0107` | Arsenal identity and active state: tab icon, Arsenal's table row tint (`--red-tint`), Arsenal's stat bars, the underline on the active match-centre tab. |
| `--red-deep #d00008` | Any red **fill carrying white text** (live pill, Arsenal shirt discs). `#ef0107` is 4.49:1 with white, just under AA. |
| `--live #ff4b50` | "Happening now": live border, live rail fill and its "now" dot. |
| `--green #1f9e57` / `--green-text #7fe0a6` | Good for Arsenal: win chip, Arsenal goal markers and minute pills, "came on". Dark text on a green fill (`--bg` on `--green` is 5.6:1); white on green is 3.45:1 and fails. |
| `--red-text #ff8a8d` | Loss chip, "came off" arrows. |
| `--amber #e08a1e` | Transfer heat (heat bars, "Close to done" chip) and half-time. |
| `--yellow-card #f2c230` | Yellow cards only. |
| `--gold`, `--blue` | The likelihood ladder and competition badges only. |

### Likelihood ladder (load-bearing, do not recolour)
Rumour `--grey`, Developing `--blue`, Advanced `--amber`, Here we go `--green`. Order is fixed by `config.LIKELIHOOD_RUNGS`. Always paired with the text label.

### Competition colours
Stored as RGB triples (`--comp-pl` purple, `--comp-ucl` blue, `--comp-fa` red, `--comp-efl` green, `--comp-cs` gold, `--comp-usc` grey) so one hue drives a badge's text and tint, the scoreboard's top band and its wash. Data colours (club kits from ESPN, table zone colours from ESPN's `note.color`) are passed inline as data and are exempt from the token rule.

---

## 4. Typography

- **System stack only** (`-apple-system, BlinkMacSystemFont, "SF Pro Text", ...`). No web fonts. SF Pro on the phone carries the broadcast feel through weight and tracking.
- **Sentence case everywhere.** No all-caps labels. Abbreviations that are football vocabulary stay as they are: FT, HT, PL, UCL, W/D/L, P/GD/Pts.
- **Tabular numerals** (`font-variant-numeric: tabular-nums`) on every score, minute, countdown, table cell and count.

| Use | Size / weight |
|---|---|
| Scoreboard score | `3rem` / 800, `-.03em` (3.2rem desktop, 2.25rem under 380px) |
| Scoreboard kick-off time | `2.4rem` / 800 |
| Page title (Matches, News, Table) | `1.85rem` / 800, `-.025em` (iOS large-title feel) |
| Section heading | `1.08rem` / 700 |
| Lead story | `1.22-1.3rem` / 800 |
| Row title, story title | `.95-1.02rem` / 600-700 |
| Body | `15px` / 400 |
| Meta | `.76-.86rem` / 500 |

Inactive controls (segments, chips, tab bar, back link, "more" links, sources) are **500**; the active one goes to 700. When everything is bold, names and scores lose their punch.

---

## 5. Space, shape, depth

- **Spacing:** 4px base. `--s1 4 / --s2 8 / --s3 12 / --s4 16 / --s5 24 / --s6 32`. Sections are `--s5` apart; page gutter `--s4` on a phone, `--s5` on desktop.
- **Radius:** `--r-sm 6` (badges, chips' inner bits), `--r-md 10` (inputs, crest tiles), `--r-lg 16` (cards, groups). Pills are `999px`.
- **Depth: surface lightness plus hairlines.** No drop shadows. The one exception is the scoreboard (section 6).
- **Touch:** every interactive element is at least 44px tall (chip rows reach it with an invisible `::after`). `-webkit-tap-highlight-color` is off and replaced by real pressed states: rows go to `--bg3`, tiles/boards/chips scale to `.97`.
- **Layout:** one column on a phone. From 900px: top nav replaces the tab bar, `1fr 340px` main + side column on Home/Matches/News, a centred 760px single column on the match centre and Table.

---

## 6. Components

### Scoreboard (`.board`): the shared match grammar
Used for the Home hero and the match-centre header. A 3px band in the competition colour runs along the top, and the same colour washes down from it (`radial-gradient` of `--comp` at 16%) over a two-stop navy gradient. On a phone it is **edge to edge** (no radius, no side borders): a broadcast header, not a card. Inside: competition and round (sentence case) with a status pill on the right; home crest + name, centre, away crest + name (64px crests); scorers mirrored around a ball icon; the match rail; a foot with venue and date.
- **Pre-match:** centre is the kick-off time (SAST) and "Today" / "Tomorrow" / "Sat 10 Oct"; the pill counts down ("in 8 days", then "in 1d 4h", "in 3h 12m").
- **Live:** centre is the score; the pill is red with a pulsing dot and the ticking minute; the board gets a `--live` edge.
- **Half time:** amber "HT" pill. **Full time:** grey "FT" pill (or ESPN's AET/pens detail); a shoot-out note sits under the score.
- **Home picks the board** in this order: a match in its live window, a result from the last 30 hours (plus a compact "Next" row under it), the next fixture, the last result.

### Match rail (`.rail`): the signature
90 minutes as a line (120 if extra time was played). HT tick at 50%. Goals sit where they happened: home side above the line, away side below. **Arsenal goals are filled green, opposition goals hollow**, red cards are small red bars. Live: the line fills `--live` up to the current minute with a pulsing "now" dot. Pre-match: no rail.

### Status pill (`.pill`)
`pill-live` (red-deep fill, white text, pulsing dot, minute), `pill-ht` (amber tint), plain (FT, postponed), `pill-soon` (countdown).

### Live minute
The snapshot only moves every 30 minutes on Pages, so the minute is computed on the phone: anchor on ESPN's `displayClock` ("67'", "45'+2'") and its `clock_at`, add elapsed whole minutes, cap the extrapolation at 12 minutes so a stale feed can never invent a "45+30'". Re-anchored on every poll. Ticks every 15s without a re-render.

### Live bar (`.livebar`)
While a match is live, every screen except Home and that match's centre shows one 44px line under the top bar: pill, "ARS 2–1 CHE", "Match centre". Tapping it opens the match.

### Recent results strip (`.strip` / `.tile`)
Horizontally scrolling tiles (112px): opponent crest, W/D/L chip plus Arsenal-first score, short club name ("Brighton", from ESPN's `shortDisplayName`), competition badge and Home/Away. `scroll-padding-inline` keeps the first tile off the screen edge. **Any scroller that contains `.sr-only` text must be `position:relative`**, or the absolutely positioned label escapes the clip, widens the page and mobile Safari/Chrome zoom the whole app out (this happened, see the 2026-10-02 handoff).

### Match rows (`.mrow`)
Grid: date block (day number 1.15rem/800 over weekday) | crest, short opponent name, competition badge and "Home, Third Round" (ellipsised) | kick-off time, or Arsenal-first score + W/D/L chip, or a live pill. The next fixture's day number is red. Grouped by month (`.month`, sentence case) into `.group` lists. Upcoming vs Results is a segmented control; competitions are chips with counts.

### Result chip (`.res`)
22px tinted square: W `--green-tint` / `--green-text`, D `--grey-tint` / `--grey-text`, L `--red-tint` / `--red-text`. Tinted, never filled. Carries a screen-reader word ("Won"). A zero in the season record fades to 35%.

### Match centre tabs
**Underline tabs** (`.mc-tabs`), sticky under the top bar, deliberately different from the segmented controls elsewhere. Tabs shown depend on the state: pre-match Preview / Line-ups; live Timeline / Line-ups / Stats / Team news; finished Timeline / Line-ups / Stats (Stats only when ESPN sent stats). The tab lives in the URL (`?tab=`), so a live re-render keeps it.

### Timeline (`.tl`)
A centre spine with the minute pill on it; home events to the left (right-aligned, icon nearest the spine), away events to the right. Names are pitch-style surnames ("De Bruyne"), with a second line for the assist, "Penalty", "Own goal" or "X off". **Goal pills:** Arsenal's are green with dark text, the opposition's are hollow (matching the rail markers). Substitutions get a green up / red down arrow icon. Cards are small CSS rectangles (`.card-ico`). HT and FT markers with the score are drawn by our code (`with_markers`), not ESPN's, because ESPN only sends them for some matches. Chronological when finished, **newest first while live**. "Match info" (kick-off SAST, venue, referee, attendance) follows as a `dl`.

### Stats (`.stat`)
Value | label | value, the larger value bold in `--text`, the smaller in `--muted`. Under it, two bars growing out from the centre, proportional to share. **Arsenal's side is red, the opponent's grey**, whichever end Arsenal are on. Possession is shown as whole percentages. Only drawn when ESPN's summary returns both sides; an all-zero payload means "not started" and hides the tab.

### Line-ups pitch (`.pitch`)
Fixed height (440px), half-pitch markings, keeper nearest the viewer. On a phone the pitch runs to the card edges. Rows come from **positions, never ESPN's `formationPlace`** (`_band()` reduces codes like `CD-L`, `LB`, `AM-R` to G/D/M/F; `test_matchcentre.py` pins it).
- **Kit colours:** Arsenal discs are `--red-deep` with white numbers. The opponent's disc takes ESPN's `color`, switching to `alternateColor` when the primary is red (Man Utd, Sunderland), and the number colour is whichever of white or `--bg` reads better on it (`kit_colours()` in `matchcentre.py`): sky blue and white kits get dark numbers.
- **Event badges** on the disc's shoulder: a ball (or a count) for goals, a yellow or red card.
- **Substituted players keep their kit colour**; a red "↓ 67'" under the name says when they went off. (Until 2026-10-02 the disc went grey, which made most of a finished XI look absent.)
- Names are surname-only, single line, ellipsised; hyphenated names never split.
- Headshots: unchanged rules. Only ESPN's declared `athlete.headshot.href`, PNG only, kit fill behind the transparent cut-out, `alt=""` because the name sits underneath, `onerror` restores the number. Sparse coverage is normal.
- Substitutes are a two-column list: shirt number, full name, goal/card marks, green "↑ 67'" for those who came on.
- The opponent XI is a collapsible `details`, closed on a phone, open on desktop; the open state survives live re-renders.

### League table (`.ltable`)
Rank with a 3px zone bar in ESPN's own zone colour (Champions League, relegation...), 22px crest, short name, P, W/D/L (420px and up), GD, Pts (800). Arsenal's row is tinted `--red-tint` and bold. A zone legend sits underneath. Premier League and Champions League league phase switch with a segmented control. Home shows a four-row window around Arsenal.

### News
- **Segmented sections:** Arsenal / Others / All / Heat. Search lives behind a search icon in the title row and opens on tap (or stays open while a query or source filter is active).
- **Morning brief:** plain card, three lines clamped, "Read the full brief" toggle.
- **Lead story:** the biggest story (source consensus, then likelihood, then insider), 1.3rem/800 headline.
- **Cards:** kicker (category, `--muted`), likelihood meter, "Insider", "N sources", relative time; headline 1.02rem/700; 200-character summary; source, clubs, player tag (gold, links to the saga).
- **Filters:** category chips with counts; "Close to done" (amber chip) shows Advanced and Here-we-go only.
- **Others:** a scrolling crest strip on a phone (a grid on desktop), stories grouped by club.
- **Heat:** scope chips and sort chips separated by a hairline; amber bars sized by heat (the stage lives only in the meter); the time sits in the card's top row.

### Navigation
Bottom tab bar on a phone (Home, Matches, News, Table) with one stroked SVG icon set (24px grid, 1.8 stroke); active = white label and red icon. Top nav from 900px with a red underline on the active item.

### Segmented control vs chips vs tabs
Three gestures, three looks: **segmented** (`.seg`, switch view, raised `--bg4` segment), **chips** (`.chip`, filter, white fill when active), **underline tabs** (match centre sections).

### States
Every list has an empty state that says what will appear and when ("Line-ups are usually confirmed about an hour before kick-off, around 12:30 SAST on Sat 10 Oct."). Loading uses quiet skeleton blocks. If the snapshot cannot load and nothing is on screen, the error says so and what to do. The top bar shows "Updated Nm ago", turning amber past two hours.

---

## 7. Content rules

- Times are SAST (`Africa/Johannesburg`), kick-offs 24-hour ("13:30").
- Relative time for news ("12m ago", "3h ago", "2d ago", then "6 Sept").
- Scores read **home first on the scoreboard** (it shows both crests) and **Arsenal first in lists** (rows, tiles), where only the opponent is named.
- British spelling and football vocabulary: kick-off, line-ups, match centre, defeat, draw.
- Error and empty copy says what happened and what to do, never apologises.

---

## 8. Accessibility baseline

- Semantic structure: one `h1` per screen (visually hidden on Home and the match centre, where the scoreboard is the title), `h2` sections, real `table` with `caption` and `abbr` headers, `nav` with `aria-current`.
- WCAG AA contrast on every text token pair listed above; white text only on `--red-deep`, never on `--red` or `--green`.
- Visible `:focus-visible` outline on everything; skip link; focus moves to the view on navigation (not on background refreshes).
- 44px minimum tap targets.
- Meaning never by colour alone: W/D/L carry letters and screen-reader words, cards and goals have text equivalents, the likelihood meter has its label, the pitch has a hidden per-player sentence ("Havertz, 1 goal, off 78'").
- `prefers-reduced-motion` turns off all animation (the live pulse included).
- Crest images are `alt=""` next to the visible club name; the crest helper falls back from ESPN's dark-UI logo to the standard logo to a monogram, never a broken image.

---

## 9. Anti-slop rules

- No em dashes anywhere (copy, comments, commits). The en dash is only a score separator ("2–1").
- No emoji as icons. One SVG icon set.
- No all-caps eyebrow labels, no explainer paragraphs under controls, no "A · B · C" meta strings.
- No gradients or colour for decoration. The scoreboard wash is the competition colour, which is information.
- No new colour literals in rules: add a token.
- No second UI, no framework, no build step.
- Every external link keeps `target="_blank" rel="noopener"`.
