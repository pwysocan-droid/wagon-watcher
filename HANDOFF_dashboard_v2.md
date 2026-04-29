# Handoff — Dashboard v2 (ticker layout)

For Claude Code, in the wagon-watcher repo. Read this AFTER
`HANDOFF_price_history_export.md` has shipped and `data/price_history.json`
is being written on every reconcile run.

This handoff builds a second dashboard surface alongside the existing
v1, adopting a stock-ticker visual language. **The v1 dashboard is not
touched.** Both surfaces will coexist for an indefinite vetting period;
the user (Patrick) will decide whether to retire v1 later.

---

## Routes

After this handoff ships:

| URL | What it serves |
|---|---|
| `https://wagon-watcher.vercel.app/` | v1 dashboard (unchanged) |
| `https://wagon-watcher.vercel.app/v2` | v2 ticker dashboard (new) |
| `https://wagon-watcher.vercel.app/data/latest.json` | unchanged |
| `https://wagon-watcher.vercel.app/data/price_history.json` | from the price-history handoff |

The v2 surface lives at `/v2` and is reachable from a small `↗ v2 ticker`
link in v1's header marginalia. Otherwise the two are independent.

## Why a second surface

v1 is a **state view** — what the inventory looks like right now. It
sorts by distance and treats every row equally. It's correct for
answering "what cars exist?" — but it's flat for "what's happening?"

v2 is a **change view** — what the inventory is doing. It sorts by
absolute % move today, surfaces price deltas as ▼/△ triangles, and
makes the eye scan for movement rather than for values. The cognitive
model is the Bloomberg Terminal MOST screen, not a parts catalog.

Both are useful. Different questions warrant different surfaces.

## What to build

A new directory `dashboard/v2/` containing:

```
dashboard/v2/
├── index.html        # the v2 surface
├── styles.css        # extracted v2 stylesheet (or inlined into index.html)
└── ticker.js         # client-side data fetch + rendering logic
```

Vercel routes `/v2` to `dashboard/v2/index.html`. No server-side code
needed; the page is pure static HTML+JS that fetches `data/latest.json`
and `data/price_history.json` and renders client-side.

### Data flow

```
On page load:
  1. fetch /data/latest.json       (current inventory snapshot)
  2. fetch /data/price_history.json (per-VIN observation series)
  3. join on VIN
  4. compute today's delta per VIN (current price vs. previous observation)
  5. compute 30d sparkline points per VIN (downsampled if >30 obs)
  6. sort by abs(today_delta_pct) DESC
  7. render the table
```

This is all client-side. The two JSON files are small enough (~80KB
combined) that fetch + parse + render is well under 500ms on a normal
connection.

### Visual specification

The mockup shipped to Patrick on 2026-04-29 is the canonical visual
reference. Pull the HTML from the conversation transcript or rebuild
from the spec below. Key details:

**Color system (extends the existing wagon-watcher design):**

- Background: `#0a0a0a` (same as v1)
- Foreground: `#f0ede8`
- Muted: `#888`
- Hairlines: `#222`
- **SBB Red `#EB0000`** — reserved for the loudest signals only:
  - Watchlist match superscript flag (¹)
  - Sub-20th-percentile pct cell border + text
  - "Watchlist matches" stat tile label and value
- **Soft crimson `#B84444`** — for price-move signals:
  - ▼ filled triangle on down moves
  - Delta percentage text on down moves
  - Sparkline stroke for cars currently below their 30d open
- White (`#f0ede8`) — for up-move triangles (hollow △)
- Dark grey (`#555`) — for flat/no-change indicators and stale-price sparklines

The color hierarchy is deliberate: a pure SBB-Red signal means "this is
a candidate to ACT on" (watchlist match, deal-zone percentile). A soft
crimson signal means "this is moving" (which is interesting but not
necessarily actionable). The eye learns to scan SBB Red first, then
soft red, then everything else.

**Typography (unchanged from v1):**

- Sans: Inter (with `system-ui` fallback)
- Mono: JetBrains Mono / IBM Plex Mono (with `ui-monospace` fallback)
- All numerics use `font-feature-settings: 'tnum', 'zero'` for tabular figures
- Two weights only: 200 (light) for big stats, 100 (extra light) for
  display numerics, 700 (bold) for emphasized prices, 500 (medium) for
  labels. Body text is 400.

**Layout primitives:**

- 4-column stat row at top: National pool / Movers today / Avg drop today / Watchlist matches
- Section bar with `§` marker on the left, period toggle (Today / 7d / 30d / All) on the right
- Single inventory table sorted by abs(today_delta_pct) DESC
- Footer with two-column marginalia: "Reading the row" legend + "Today's session" poll log

**The inventory table columns (left to right):**

1. **VIN** — monospace, underlined, links to MBUSA listing. Watchlist matches get a `¹` superscript in SBB Red.
2. **Yr · Dealer · Color** — model year, dealer name, color. Greyed if outside criteria.
3. **Miles** — right-aligned, tabular figures.
4. **30d sparkline** — 60×14px SVG, soft-crimson stroke if currently below 30d open, grey if flat or above.
5. **Asking · Δ today** — two-line cell. Top line: current asking price (bold, large). Bottom line: triangle + dollar delta + percent delta (small, soft crimson for down moves, white for up).
6. **Pct** — bordered "tab" showing fairprice percentile. SBB-Red border + text for sub-20th-percentile values.
7. **Seen** — days since the watcher first observed this VIN.

**Row treatment:**

- Active rows (had a price change today): subtle warm-grey tint `rgba(240, 237, 232, 0.025)` background, slightly more padding (11px vs 9px).
- Static rows (no change today): transparent background, normal padding.
- Hover: rows lift by ~2.5x background opacity.

**Triangle convention (1929 NYSE):**

- ▼ filled in soft crimson `#B84444` for down
- △ hollow with soft white border for up
- Horizontal dash `─` in dark grey for flat
- Triangle is rendered via CSS borders (no SVG needed for this primitive)

**Sparkline convention:**

```html
<svg width="60" height="14" viewBox="0 0 60 14">
  <polyline fill="none" stroke="#B84444" stroke-width="1" points="..."/>
</svg>
```

Coordinates are normalized: 0 = top of cell (highest price in the
30d window), 14 = bottom (lowest price). Each observation gets an
x-coordinate proportional to its observed_at timestamp position
within the 30d window. Linear interpolation between observations.

If there are fewer than 2 observations for a VIN, render a flat
horizontal line at y=7 in dark grey (`#555`).

### The period toggle (Today / 7d / 30d / All)

Wired to the table sort and the delta computation:

- **Today** (default): sort by abs(price_delta vs yesterday's last observation). Show only rows with a non-zero today move; collapse the rest into a `... 22 more static listings` row.
- **7d**: sort by abs(price_delta_pct vs 7 days ago). Show all rows where 7d delta is non-zero.
- **30d**: sort by abs(price_delta_pct vs 30 days ago). Show all rows.
- **All**: sort by abs(price_delta_pct vs first_seen). Show all rows.

Toggling re-renders client-side; no server roundtrip. URL query
parameter `?period=7d` for shareable state. Default is today.

### "Movers today" stat card calculation

Show count of VINs where today's delta is non-zero. Sub-text shows
the breakdown: "8 down · 2 up". If today has no movers yet, show "0"
and sub-text "quiet day so far."

### Avg drop today

Compute mean of all today's price_delta_pct values where delta is
negative. If zero down-movers, show "—". Sub-text could note regional
patterns ("East Coast leading") if a regional cluster is detectable —
but for v2, just leave the sub-text empty when no obvious pattern.
Don't fake insight.

### What v1 needs (one tiny change)

In v1's header marginalia (top-right `<div class="meta">`), add one
new line at the end:

```html
<div><a href="/v2" style="color: var(--muted);">↗ v2 ticker</a></div>
```

Only change to v1. Otherwise v1 is untouched.

## Implementation order

1. **Set up the route.** Configure `vercel.json` (or whatever's in use)
   to map `/v2` to `dashboard/v2/index.html`. Verify the empty page
   loads at the new URL before adding logic.
2. **Build the page shell** — header, stat row, section bar, empty
   table, footer. Use static placeholder data so the design is right
   before wiring data.
3. **Wire the data fetch** — load both JSON files in parallel,
   join on VIN, log to console for verification.
4. **Render the table** with real data, default Today sort.
5. **Add the period toggle** — Today/7d/30d/All with re-sort+re-render.
6. **Polish: sparklines, triangle indicators, percentile borders.**
7. **Add the v1 → v2 link** in v1's marginalia.

Each step should leave the page in a working state. Commit at each
step.

## What's NOT in this handoff

- No new data fields. Everything needed is in `latest.json` +
  `price_history.json`.
- No watchlist editing UI. The watchlist remains DB-managed.
- No notification/alert surface. Alerts live in their own files.
- No annotation system (e.g., user marking a VIN as "rejected for
  Carfax reasons"). Per the user's decision: the watcher surfaces
  candidates; humans vet them externally.
- No replacement of v1. Both surfaces coexist.
- No mobile-specific layout. Desktop-first; mobile gets the same
  layout with a horizontal scroll on the table if needed.
- No real-time websocket updates. Page reload is the refresh
  mechanism. (The data updates every ~30 minutes anyway.)

## Tests

Three tests are sufficient:

1. **Page loads at `/v2`** — basic smoke test, reachable URL, no console errors
2. **Today sort puts movers first** — given fixture data with one big mover and one static row, verify mover renders above static
3. **Period toggle changes sort order** — toggling to 30d re-sorts based on 30d delta, not today delta

Use Playwright or whatever framework is already in the repo's frontend
test pattern. If no frontend tests exist yet, mirror the pattern from
backend tests.

## Commit hygiene

Suggested commit sequence:

1. `vercel: add /v2 route to dashboard/v2/index.html`
2. `dashboard/v2: page shell with placeholder data`
3. `dashboard/v2: fetch latest.json + price_history.json, log joined data`
4. `dashboard/v2: render inventory table with today's deltas`
5. `dashboard/v2: period toggle (today/7d/30d/all) with client-side re-sort`
6. `dashboard/v2: sparklines, triangle indicators, percentile borders`
7. `dashboard/v1: link to /v2 in header marginalia`

Each commit leaves the system in a working state.

---

## Verification after deploy

After Vercel deploys the changes:

1. `https://wagon-watcher.vercel.app/v2` loads with current inventory
2. The Cary wagon (W1KLH6FB0SA147147) shows at the top of the table
   if it had a move today
3. Today's movers display with soft-crimson triangles and percentages
4. Watchlist matches show the `¹` superscript in SBB Red
5. Sub-20th-percentile cells show the SBB Red bordered box
6. The period toggle (Today/7d/30d/All) re-sorts the table
7. v1 still works unchanged at `/`
8. v1 has a small `↗ v2 ticker` link in its top-right marginalia

If all eight pass, v2 is shipped. The user can then make decisions
about whether to retire v1 over the next few weeks of side-by-side
use.

Total scope: roughly 60-90 minutes of work, smaller than v1 was
because most of the design is already specified in the mockup.
