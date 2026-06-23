# Arsenal Tracker: Design System Contract

This is the persistent design contract for the Arsenal Tracker app. Read it before touching `static/style.css` or any template. It records what the design actually is today, and marks proposed conventions clearly so we do not drift.

Values labelled **(real)** are extracted from the current `static/style.css`. Values labelled **(proposed)** are sensible defaults to fill gaps, and should be adopted deliberately, not assumed to already exist.

---

## 1. Purpose & personality

A personal Arsenal FC news and transfer tracker. Two main pages: Arsenal news (`/`) and Other Teams / Europe transfers (`/europe`), plus a combined `/all` feed and per-player saga timelines (`/saga/<player>`).

Personality: a clean, fast, content-focused news app with a strong Arsenal identity. Think a broadcast sports desk at night: dark surface, Arsenal red as the signal colour, dense but scannable cards, live match strip up top. It is "broadcast dark", not a glossy marketing site.

Principles:
- Content first. The story headline is the hero of every card, not chrome.
- Scannable at a glance. Category, likelihood, source consensus and timestamp all readable without clicking.
- Fast. Server-rendered, no client framework, minimal JavaScript.
- Arsenal red is a signal, not wallpaper. Use it for identity, active states and urgency, not large fills.

---

## 2. Tech stack

- **Flask + Jinja2 templates + plain CSS.** No React, no Vue, no Tailwind, no build step.
- A single stylesheet: `static/style.css`. No preprocessor, no PostCSS.
- Templates live in `templates/`. Shared UI is built from Jinja macros in `templates/_macros.html` (topbar, livestrip, meter, card, rail widgets, bottomnav).
- Because there is no build step, **design tokens are CSS custom properties on `:root`**. This is already the pattern in the file. Keep it. Do not introduce a CSS framework or a token build tool to "improve" this.
- Progressive web app: `manifest.webmanifest` and `sw.js` served from `static/`.

Rule: any new colour, radius or shadow goes through a `:root` variable, not a hard-coded literal in a rule. See section 10.

---

## 3. Colour palette

All values below are **(real)**, taken verbatim from `:root` in `static/style.css`.

### Surfaces and structure
| Token | Value | Role |
|-------|-------|------|
| `--bg` | `#0a0e16` | App background (near-black navy). Body also layers two faint radial gradients: red top-right, blue top-left. |
| `--bg2` | `#121826` | Card and widget surface. |
| `--bg3` | `#1a2233` | Raised surface: pills, inputs, hover fills, meter track. |
| `--line` | `#232c40` | Borders and dividers. |

### Text
| Token | Value | Role |
|-------|-------|------|
| `--text` | `#e7ecf3` | Primary text. |
| `--muted` | `#8b97ad` | Secondary text: summaries, sources, labels. |
| `--dim` | `#5e6b82` | Tertiary text: timestamps, counts, placeholders. |

### Brand and accents
| Token | Value | Role |
|-------|-------|------|
| `--red` | `#ef0107` | **Arsenal red. Primary brand colour.** Active nav, hero tag, matchday accents, category spine for injuries. This is the official Arsenal red. |
| `--red2` | `#ff2b30` | Brighter red for hover and link emphasis. |
| `--gold` | `#e0a93a` | Transfers accent: category, player tags, done deals. |
| `--blue` | `#2f7ed8` | Informational / insider accent: filter submit button, insider glow, match-results category. |
| `--green` | `#1f9e57` | Positive / "done" state: morning brief, top likelihood rung, win badge. |
| `--amber` | `#e08a1e` | Mid-tier likelihood, advanced-rumour heat, the rung toggle. |
| `--grey` | `#7c889d` | Neutral / lowest likelihood rung, draw badge. |

### Semantic roles (use these, not raw hexes)
- **Brand / identity:** `--red`. Hover and emphasis: `--red2`.
- **Transfers domain:** `--gold`.
- **Match / informational:** `--blue`.
- **Success / confirmed:** `--green`.
- **Warning / in-progress:** `--amber`.
- **Neutral / unknown:** `--grey`.
- **Loss / negative:** `--red`.

### Likelihood ladder colour scale (real, load-bearing)
The transfer likelihood ladder maps four rungs to a deliberate cool-to-warm-to-go scale:
- Rumour: `--grey` `#7c889d`
- Developing: `--blue` `#2f7ed8`
- Advanced: `--amber` `#e08a1e`
- Here we go: `--green` `#1f9e57`

Do not recolour these rungs casually. The progression (neutral, info, warning, go) is the meaning.

### Shape and depth tokens (real)
| Token | Value | Role |
|-------|-------|------|
| `--radius` | `14px` | Standard card / widget radius. |
| `--shadow` | `0 8px 30px rgba(0,0,0,.45)` | Standard elevation shadow. |

---

## 4. Typography

**Font stack (real):**
```
-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
```
System font stack only. No web fonts, no font loading cost. Keep it this way for speed. `-webkit-font-smoothing: antialiased` is on for crisp text on dark backgrounds.

**Weights in use (real):** 400 (body), 500, 600, 700, 800. 800 is the strong/heading weight (brand name, hero title, card titles, widget heads, category pills). There is no 900.

**Type scale (real, observed across the stylesheet).** Sizes are in `rem` unless noted.

| Use | Size | Weight |
|-----|------|--------|
| Hero title | `1.5rem` (mobile `1.25rem`) | 800 |
| Saga page H1 | `1.6rem` | (default heading) |
| Europe section heading | `1.3rem` | (default) |
| Club section head | `1.05rem` | (default) |
| Card title | `1.02rem` | 700 |
| Brand name | `0.98rem` | 800 |
| Saga / timeline title | `0.98rem` | 700 |
| Body summary | `0.86rem` | 400 |
| Source, clubs, tags | `0.74`-`0.76rem` | 600 |
| Pills, labels, badges | `0.62`-`0.68rem` | 800, uppercase, letter-spaced |
| Live strip label | `0.62rem` | 700, `letter-spacing:1.5px` |

**Line height (real):** body copy uses `1.45`-`1.55`. Titles tighten to `1.2`-`1.32`.

**Letter spacing (real):** small uppercase labels and the brand name use positive tracking (`0.4px` to `2px`). Body text uses none.

**Convention:** heading hierarchy is carried by **weight and size together**, not colour. Most headings stay `--text`; colour is reserved for accents and states.

---

## 5. Spacing & layout

**Page shell (real):** `.layout` is `max-width: 1200px`, centred, `padding: 16px`, a two-column CSS grid: `1fr 320px` (main feed plus a 320px right rail), `gap: 18px`. Below `900px` it collapses to a single column and the rail moves below the feed (`order: 2`).

**Spacing rhythm (real, observed):** the app uses a loose 4 / 8 / 12 / 14 / 16 / 18px step. There is no formal token scale.

> **(Proposed)** Introduce a spacing scale as `:root` variables to formalise the rhythm already in use:
> `--s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px;`
> Adopt gradually; do not mass-rewrite working rules.

**Feed (real):** `.feed` is a vertical flex column, `gap: 11px`. Cards stack; they are not a multi-column masonry grid. This keeps the newest-first reading order obvious.

**Crest wall (real, Europe page):** `.crestwall` is an auto-fill grid, `minmax(98px, 1fr)`, `gap: 8px`. This is the one place a tile grid is used.

**Sticky chrome (real):** the top bar is `position: sticky; top: 0` with a blurred translucent background (`backdrop-filter: blur(14px)`). On mobile a fixed bottom nav appears; the body reserves `padding-bottom: 70px` so content is never hidden behind it.

**Live strip (real):** a horizontally scrollable row of `.ls-block` cells (next match, last result, form, table position) directly under the top bar.

**Saga timeline (real):** a single left-rail vertical timeline. `.timeline` has a `2px` vertical line via `::before`; each `.tl-row` has a `.tl-dot` coloured by rung, with a glow on the top rung.

---

## 6. Component conventions

### News / story card (`.card`, macro `card()`)
- Surface `--bg2`, `1px` border `--line`, radius `12px`, padding `13px 15px`.
- **Left colour spine** (`border-left: 3px`) encodes category: transfers gold, injuries red, match-results blue, default dim.
- **Insider stories** get `.insider-glow`: a blue ring and soft blue outer glow.
- Structure: meta row (category pill, likelihood meter, insider badge, source-consensus badge, timestamp), then `h2.card-title` link, then optional summary (truncated at 200 chars), then a foot row (source, clubs, player tag).
- **States:**
  - Default: subtle, opacity rises in via the `rise` keyframe on load (`translateY(8px)` to settled).
  - Hover: `translateY(-2px)`, standard shadow, border brightens to `--dim`. Transition `0.15s`.
  - Title link hover: text turns `--red2`.
- Card titles are real `<h2>` elements wrapping `<a>` with `target="_blank" rel="noopener"`. Keep `rel="noopener"` on every external link.

### Hero (`.hero`)
The lead story, picked by `pick_hero()` (source consensus, then likelihood, then freshness). Larger surface with a gradient, a red radial wash top-right, a red `.hero-tag` label, a `1.5rem` title, and the same lift-on-hover behaviour. One hero maximum, only on the unfiltered "All" view.

### Likelihood meter / ladder (`.meter`, macro `meter()`)
The signature ranking UI. Four `7px` tall segments (`.seg`, `14px` wide) plus a text label (`em`). Segments fill cumulatively up to the rung index; each "on" segment takes its rung colour (`.s0` grey, `.s1` blue, `.s2` amber, `.s3` green). The label colour matches the rung. Empty segments sit on the `--bg3` track. Segment fill animates over `0.5s`.

Rung order is fixed by config: `Rumour, Developing, Advanced, Here we go`. "Here we go" is the Fabrizio Romano confirmation phrase and is the top, green rung. Do not rename or reorder rungs in CSS independently of `config.LIKELIHOOD_RUNGS`.

### Rumour-heat rows (`.heat-row`, rail widget)
A horizontal bar chart: player name, a fill bar coloured by best likelihood (`.hb-rumour` grey through `.hb-here-we-go` green), and a mention count. Bars grow in via the `grow` keyframe. The fill class mirrors the ladder scale, keeping one consistent colour language for "how real is this".

### Badges and pills
- **Category pill** (`.cat-pill`): tiny, uppercase, letter-spaced, `--bg3` background by default; per-category tinted variants (gold/red/blue) use a low-alpha background plus the matching accent text.
- **Insider badge** (`.insider`): blue-tinted, bordered, "insider" label.
- **Consensus badge** (`.consensus`): green, shows source count, tooltip lists sources.
- **Player tag** (`.player-tag`): gold pill linking to the player saga.
- **Form chips** (`.f`): `18px` squares, win green / draw grey / loss red.
- Convention: badges are small, uppercase or compact, and use low-alpha tinted backgrounds rather than solid fills, except the active brand red.

### Links and nav
- Global default: `a { color: inherit; text-decoration: none }`. Links are styled by context, not a global link colour.
- **Page nav pill** (`.pagelink`): muted by default; hover lifts to `--text` on `--bg3`; **active is solid `--red` with white text and a red glow shadow.**
- **Tabs** (`.tab`): category filters; muted, bordered; active is solid red. The "rung toggle" tab is the amber exception.
- **Back link** (`.back`): muted, hover `--red2`.

### Rail widgets (`.widget`)
Uniform container: `--bg2`, `--line` border, `--radius`, padding `13px 14px`, a `widget-head` (800 weight, emoji prefix). Widgets: Rumour Heat, Done Deals, Injury Room, Premier League mini-table. Rows inside are full-width links with top-border dividers.

---

## 7. Content density

This is a news feed; density and scannability are the point.

- **Newest first, vertical stack.** One column of cards, not a grid. Reading order is time order.
- **Every card answers four questions at a glance:** what kind of story (category pill + spine colour), how likely (meter), how trusted (source count + insider badge), how fresh (relative timestamp, right-aligned via `margin-left: auto`).
- **Timestamps are relative** via the `time_ago` filter: `just now`, `Nm ago`, `Nh ago`, `Nd ago`, then falls back to `DD Mon` after a week. Keep this human format; do not show raw ISO timestamps in the feed.
- **Summaries are truncated** (200 chars in cards) with an ellipsis. The headline does the work; the summary is support.
- **Tints carry meaning, not decoration.** Gold means transfer, red means injury or urgency, blue means info or insider, green means confirmed. Do not add tints that do not map to one of these meanings.
- **One hero, then the feed.** Avoid multiple competing focal points on a page.
- Keep the rail for aggregates (heat, done deals, injuries, table). The main column is for the chronological story stream.

---

## 8. Accessibility baseline

- **Semantic HTML (real and required):** cards are `<article>`, the top bar is `<header>`, nav is `<nav>`, widgets are `<section>` with a heading, the league widget is a real `<table>`. Card titles are `<h2>`. Keep this. Do not replace semantic elements with bare `<div>`s.
- **Heading order:** maintain a sane hierarchy per page (one H1 of meaning, section H2s). The saga page uses H1; index uses H2 card titles under a hero. Avoid skipping levels when adding sections.
- **Contrast:** primary text `--text` on `--bg`/`--bg2` is strong. `--muted` on dark passes for body secondary text; **`--dim` on dark is borderline and should be reserved for non-essential metadata** (timestamps, counts), never for content a user must read. Do not put `--dim` text on `--bg3`.
  - **(Proposed)** Spot-check `--dim` and `--muted` against AA (4.5:1 for body, 3:1 for large text) and nudge `--dim` lighter if any essential text uses it.
- **Focus states (gap):** there are no explicit `:focus` / `:focus-visible` styles in the stylesheet today. Interactive elements rely on default UA focus rings, and the global `a { text-decoration: none }` removes a cue.
  - **(Proposed, recommended)** Add a single visible focus style:
    ```css
    a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible {
      outline: 2px solid var(--red2);
      outline-offset: 2px;
    }
    ```
- **Hit targets:** the refresh button is `34px`; mobile bottom-nav items are full-flex. Aim for a minimum interactive target of around `40px` on touch where practical. **(Proposed)**
- **Motion:** several entrance animations exist (`rise`, `grow`, `pulse`). **(Proposed)** Respect reduced motion:
    ```css
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
    }
    ```
- **Images:** crest images carry `alt` text and `loading="lazy"` with a monogram fallback on error (real). Keep alt text on any new imagery.
- **Colour is never the only signal:** likelihood always pairs the colour scale with a text label; form chips show the letter, not just the colour. Keep this pattern: never encode meaning in colour alone.

---

## 9. Anti-slop rules

- **No em dashes anywhere.** Not in templates, copy, comments, commit messages or this file. Use commas, full stops, colons, semicolons or "and". (The app already uses an en dash `–` only as a score separator, for example `2–1`, which is correct typography for scores and is fine.)
- **British spelling** in all copy: colour, behaviour, organise, centre.
- **No new colour literals.** If you need a colour, it is either already a `:root` token or you add one. No `#xxxxxx` buried in a rule.
- **Do not add a CSS framework or build step.** Plain CSS plus `:root` variables is the contract. No Tailwind, no SCSS, no PostCSS.
- **No generic AI-dashboard look:** avoid full-bleed purple-to-blue gradients, glassmorphism everywhere, oversized rounded "card soup", and giant empty hero banners with no content. This is a dense news desk, not a SaaS landing page.
- **Arsenal red is a signal.** Do not flood large surfaces with red. It marks identity, active state and urgency only.
- **Respect the meaning of the accent colours** (section 3). Do not use gold for a non-transfer thing or green for something that is not confirmed/positive.
- **Keep the feed a single column.** Do not turn the story stream into a multi-column grid; it breaks chronological scanning.
- **One hero per page, on the unfiltered view only.** Do not stack multiple hero blocks.
- **No decorative icons without meaning.** The emoji prefixes map to real domains (fire = heat, tick = done, bandage = injuries). Do not sprinkle decorative ones.
- **Truncate, do not dump.** Long summaries are clipped on purpose. Do not remove truncation to show full article bodies in the feed.
- **Every external link keeps `target="_blank" rel="noopener"`.**

---

## 10. Token consolidation note (plain CSS, no Tailwind)

The colour layer is already well consolidated: nearly everything routes through the `:root` palette. Two gaps remain, and fixing them keeps theming consistent and makes a future light mode or alternate accent trivial.

1. **Inline tint literals.** Several tints are written as raw `rgba()` of the brand hexes scattered through rules, for example the red wash `rgba(239,1,7,.12)`, gold `rgba(224,169,58,.16)`, blue `rgba(47,126,216,.18)`, green text `#7fe0a6`. These repeat the palette by hand.
   - **(Proposed)** Promote the recurring tints and accent-text shades to named tokens, for example:
     ```css
     :root {
       --red-wash: rgba(239,1,7,.12);
       --gold-tint: rgba(224,169,58,.16);
       --blue-tint: rgba(47,126,216,.18);
       --green-tint: rgba(31,158,87,.16);
       --green-text: #7fe0a6;
       --blue-text: #6fa8e6;
     }
     ```
     Then reference the tokens instead of repeating literals. This is the single highest-value tidy-up.

2. **Club brand colours** (`.club-man-city` and friends) are intentional per-club hexes and do **not** need to become global tokens; they are data, not theme. Leave them as scoped rules.

**Rule going forward:** any colour used in more than one rule must be a `:root` variable. New surfaces, accents and tints are added to `:root` first, then referenced. This keeps the no-build-step plain-CSS approach maintainable and makes re-theming a one-block change.
