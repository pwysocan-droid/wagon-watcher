# PROJECT.md — Mercedes E-Class Wagon CPO Watcher

## What this is

A scheduled scraper that watches mbusa.com CPO inventory for E-Class wagons,
records every listing and every price change to SQLite, commits the database
back to this repo on each run, and notifies me about meaningful events.

Architecture: GitHub Actions cron + SQLite + git history as the dataset
("git scraping" pattern, per Simon Willison). No external services beyond
GitHub itself and one notification channel.

## Stop and confirm before building

**Recon is complete as of 2026-04-25.** `fixtures/endpoint_notes.md`
and `fixtures/sample_response.json` should both exist in the repo.
If they don't, recreate them from the captured data before any code
is written. Do not attempt to re-discover the endpoint — it has been
mapped.

## The endpoint (confirmed working 2026-04-25)

**URL:** `https://nafta-service.mbusa.com/api/inv/v1/en_us/used/vehicles/search`

**Method:** GET. No auth headers required. No session cookie. Public.

**Canonical query (the watcher's target):**
```
?count=12
&distance=ANY
&invType=cpo
&class=E
&model=E450S4
&bodyStyleId=WGN
&resvOnly=false
&sortBy=distance-asc
&start=1
&withFilters=true
&zip=90210
```

**Important API quirks (verified 2026-04-26 by direct probing — supersedes
original recon, which got both `count` and `start` wrong):**

- `count` is **NOT** hard-capped at 12. `count=24` works fine. `count=30+`
  silently returns truncated results.
- `start` is **NOT** an offset. Different `start` values return disjoint
  12-record windows; `start>=12` returns 0 records. Original recon's
  "next page = start + count" rule does not work.
- `paging.totalCount` is unreliable — reports 53 wagons but the
  modelDesignation facet says only 34 E450S4 listings exist.
- `withFilters=true` is required. `withFilters=false` returns 400.
- **The workaround:** make TWO calls per poll, union by VIN —
  `count=12, start=1` and `count=24, start=1` together return ~36 unique
  VINs (deterministic across 3-run stability check). 4 requests/hour at
  30-min polling. See `fixtures/endpoint_notes.md` for full details.

## Response structure (confirmed)

Top-level shape:
```
result.pagedVehicles.records[]      ← the vehicles array
result.pagedVehicles.paging         ← { totalCount, currentOffset, currentCount }
result.facets                       ← aggregations (color, dealer, year, etc.)
status.code                         ← 200 on success
```

Per-vehicle field mapping (the parser needs this).

**Critical structural rule (verified against `fixtures/sample_response.json`,
2026-04-25):** the "live" per-vehicle data — mileage, photos, options, full
dealer info — lives under `record.usedVehicleAttributes.*`, NOT at the record
root. The first record of a response often *duplicates* these to top-level
keys, but records 2+ do not. **Always read from `record.usedVehicleAttributes.*`
for these fields.** The original recon notes documented top-level paths because
they were eyeballed on record #1 only — that was a bug, fixed below.

| What we need | Path in JSON | Notes |
|---|---|---|
| VIN | `record.vin` | unique key |
| Year | `record.year` | string, not int — cast |
| Model name | `record.modelName` | e.g. "E 450 4MATIC All-Terrain" |
| Trim/model code | `record.modelId` | "E450S4" |
| Body style | `record.bodyStyleId` | "WGN" |
| **Asking price** | `record.msrp` | top-level. Dealer asking price (NOT original MSRP — see naming gotcha). Mirrored at `record.usedVehicleAttributes.dsrp`. |
| Mileage | `record.usedVehicleAttributes.mileage` | float, in miles |
| Exterior color (display) | `record.paint.name` | e.g. "Obsidian Black metallic" |
| Exterior color (code) | `record.exteriorMetaColor` | e.g. "BLK" |
| Interior color | `record.upholstery.name` | |
| Engine | `record.engine` | |
| CPO flag | `record.usedVehicleAttributes.certified` | boolean — should always be `true` for our query |
| Dealer name | `record.usedVehicleAttributes.dealer.name` | top-level `record.dealer.name` is unreliable; only present on record #1 |
| Dealer ID | `record.dealerId` | top-level. Also at `record.usedVehicleAttributes.dealer.id`. |
| Dealer ZIP | `record.usedVehicleAttributes.dealer.address[0].zip` | |
| Dealer state | `record.usedVehicleAttributes.dealer.address[0].state` | |
| Distance from query ZIP | `record.usedVehicleAttributes.dealer.address[0].location.dist` | string, in miles |
| Dealer URL | `record.usedVehicleAttributes.dealer.url` | for cross-source price check |
| Lead photo | `record.usedVehicleAttributes.images[0]` | first real photo. (`exteriorBaseImage` was mentioned in original recon as a stock-render fallback but is absent from every record in the live fixture — ignore.) |
| Stock ID | `record.stockId` | dealer's internal stock number. Also at `record.usedVehicleAttributes.stockId`. |
| Options list | `record.usedVehicleAttributes.optionList[]` | array of `{code, text}` |

**Critical naming gotcha:** The field literally named `msrp` in the
response is NOT the original manufacturer's suggested retail price.
It is the dealer's current asking price. There is no field for the
original MSRP. This is misleading but consistent across every record
in the response.

## Repo layout

```
.
├── .github/workflows/watch.yml    # cron every 30 min
├── PROJECT.md                     # this file
├── REPLAY.md                      # how to replay a saved snapshot locally (you write this)
├── recon.py                       # one-shot exploratory script (you write a stub)
├── scrape.py                      # fetches + parses; pure function, no DB writes
├── reconcile.py                   # diffs scrape output against DB state
├── db.py                          # schema, migrations, helpers
├── notify.py                      # Pushover dispatcher
├── digest.py                      # weekly markdown summary generator
├── fairprice.py                   # percentile-rank scoring
├── data/
│   ├── inventory.db               # SQLite, committed each run
│   └── latest.json                # current active inventory, pretty-printed
├── raw_snapshots/                 # gzipped raw JSON, one per run, forever
├── fixtures/
│   ├── endpoint_notes.md
│   └── sample_response.json
└── tests/
    ├── test_scrape.py
    ├── test_reconcile.py
    └── test_fairprice.py
```

## Database schema

Two core tables plus three support tables. SQLite, with `PRAGMA journal_mode=WAL`.

### `listings` (one row per VIN ever seen)
- `vin` TEXT PRIMARY KEY
- `first_seen` TIMESTAMP
- `last_seen` TIMESTAMP
- `status` TEXT  -- 'active' | 'gone' | 'reappeared'
- `gone_at` TIMESTAMP NULL
- `dealer_name` TEXT
- `dealer_zip` TEXT
- `dealer_state` TEXT
- `year` INTEGER
- `model` TEXT
- `trim` TEXT
- `body_style` TEXT
- `exterior_color` TEXT
- `interior_color` TEXT
- `mileage_first_seen` INTEGER
- `photo_url` TEXT  -- lead photo
- `listing_url` TEXT
- `options_json` TEXT  -- raw options blob from listing
- `vin_decode_json` TEXT NULL  -- cached NHTSA decode

### `price_history` (one row per observed change)
- `id` INTEGER PRIMARY KEY
- `vin` TEXT  -- FK
- `observed_at` TIMESTAMP
- `price` INTEGER
- `mileage` INTEGER
- Insert only when price OR mileage differs from the most recent row for this VIN.
- Index on `(vin, observed_at)`.

### `notes` (my manual annotations, keyed by VIN)
- `id` INTEGER PRIMARY KEY
- `vin` TEXT
- `created_at` TIMESTAMP
- `note` TEXT
- `tags` TEXT  -- comma-separated, e.g. "interested,called-dealer"

### `runs` (every scraper execution)
- `id` INTEGER PRIMARY KEY
- `started_at` TIMESTAMP
- `finished_at` TIMESTAMP
- `listings_found` INTEGER
- `new_count` INTEGER
- `changed_count` INTEGER
- `gone_count` INTEGER
- `reappeared_count` INTEGER
- `duration_ms` INTEGER
- `status` TEXT  -- 'ok' | 'aborted' | 'error'
- `error_message` TEXT NULL

### `watchlist` (specs or VINs I'm tracking closely)
- `id` INTEGER PRIMARY KEY
- `kind` TEXT  -- 'vin' | 'spec'
- `vin` TEXT NULL
- `spec_json` TEXT NULL  -- e.g. {"min_year":2022,"max_mileage":25000,"max_price":70000}
- `label` TEXT
- `created_at` TIMESTAMP
- `active` INTEGER  -- 0/1

## Pipeline

1. `scrape.py` hits the JSON endpoint (per `fixtures/endpoint_notes.md`),
   handles pagination, returns `list[dict]`. Pure function. Never touches the DB.
   Always saves the raw response, gzipped, to `raw_snapshots/YYYYMMDD_HHMMSS.json.gz`.
2. `reconcile.py` takes that list + a DB connection, computes the diff against
   current state, writes new listings, appends to `price_history` only on change,
   marks vanished VINs as `gone`, marks returning VINs as `reappeared`.
3. `notify.py` reads the events emitted by `reconcile.py` and routes them by
   severity (see "Notification rules" below).
4. The workflow commits `data/inventory.db`, `data/latest.json`, and the new
   `raw_snapshots/*.gz` file back to the repo.

## Health check (abort, don't corrupt)

Before reconcile writes anything, run an assertion: if `listings_found == 0` OR
`listings_found < 0.5 * <last successful run's count>`, abort. Write a `runs`
row with `status='aborted'`, send a high-priority notification to me, and exit
nonzero so the workflow fails visibly. Do NOT write the bad data to the DB.

## Notification rules

**Channel: Pushover.** Single channel, single API. Confirmed
2026-04-27. Setup details in the section below.

Tier 1 (Pushover priority 1 or 2, bypasses quiet hours):
- New listing matching any active `watchlist` entry → priority 1
- Price drop ≥7% on any active listing → priority 1
- Reappeared VIN (was `gone`, now back) → priority 1
- Scraper aborted (health check failed) → **priority 2**, with
  `retry=30, expire=3600` so it re-alerts every 30 seconds for up
  to one hour until acknowledged

Tier 2 (Pushover priority 0, normal):
- Any new listing
- Price drop 3–7%
- Same VIN, new dealer (intra-network transfer)
- Mileage decreased on existing VIN (data anomaly worth knowing)

Tier 3 (Pushover priority -2, silent — appears in app history but
no notification fires):
- VIN went `gone` (i.e., probably sold)
- Price drop <3%

Notification payload includes: lead photo (Pushover supports image
attachments natively), asking price, percentile rank from
`fairprice.py`, days listed, dealer name + state, and a deep link
to the listing.

### Pushover setup (one-time)

1. Create account at https://pushover.net (free 30-day trial,
   then $5 one-time per platform license — iOS app required)
2. Install the iOS app and log in to confirm device
3. From the dashboard, create an Application/API Token named
   `wagon-watcher`. Optionally upload a small icon.
4. Two strings needed by the watcher:
   - **User key** (top of dashboard, 30 chars, identifies you)
   - **Application API token** (30 chars, identifies the app)
5. Add both to GitHub Actions secrets:
   - `PUSHOVER_USER_KEY`
   - `PUSHOVER_API_TOKEN`
6. Do NOT add to `.env` — the watcher only ever runs in CI

### Why Pushover over alternatives

Considered and rejected at 2026-04-27: Discord webhook (free but
requires Discord client), ntfy.sh (free but no iOS-native
priority mapping), email (too slow), SMS (carrier-throttled).

Pushover wins on: sub-second median delivery latency, true
priority levels that map to OS-level iOS behavior, native image
attachment support, persistent notification history, per-device
quiet-hours configuration, emergency-priority retry-loop for
critical failures (the scraper-aborted case).

## Fair-price scoring (`fairprice.py`)

For each currently-active VIN, compute its percentile rank against comparable
listings (same model year ±1, same trim, mileage within ±15k). Return an
integer 0–99 (lower = cheaper relative to comps). Run nightly via a separate
workflow step; cache the result on the `listings` row in a `fair_price_pct`
column (add to schema). Surface the score in every notification.

If fewer than 5 comps exist, return NULL and the notification says "insufficient
comps" rather than a bogus percentile. Wagon inventory is thin; this will happen.

**Reality check from April 2026 recon:** national CPO E450 All-Terrain
inventory totals 34 cars. Strict comp matching (same year ±1, same
trim, ±15k mileage) will produce <5 comps for the majority of listings.
Recommend a tiered comp strategy: try strict first, fall back to year
±2 / mileage ±25k, fall back to year ±3 / mileage ±40k. Tag the
percentile with the comp-pool tier used (`pct_strict`, `pct_loose`,
`pct_broad`) so the notification can convey confidence appropriately.

## Weekly digest (`digest.py`)

Runs Sundays at 9am local time via a separate cron in the same workflow file.
Generates `digest/YYYY-WW.md` and commits it. Contents:

- Headline counts: new listings, price drops, gone, reappeared
- Total $ in price reductions this week
- Median asking price this week vs last week vs 4 weeks ago
- Top 5 stalest active listings (most days on market) with current price
- Top 5 biggest price drops this week
- Any watchlist hits

Pure markdown. No notifications — this is the file I read on Sundays.

## VIN decode

On first sight of a new VIN, call NHTSA's free vPIC API:
`https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/<VIN>?format=json`
Cache the full response in `listings.vin_decode_json`. No auth, no rate limit
worth worrying about. Best-effort — if it fails, log and continue; don't block
the run.

## Geographic enrichment

Add a `distance_miles` column to `listings`. Compute from my home ZIP (90210)
to `dealer_zip` using a static lookup table of US ZIP centroids. Bundle a CSV
of ZIP centroids in the repo (small, ~3MB) rather than calling a geocoding API.
Recompute on first sight only.

## Modes

`scrape.py` and `reconcile.py` should both honor an env var `DRY_RUN=1`:
- Read fixtures instead of hitting the network
- Print all DB writes that would happen, but don't commit them
- Print all notifications that would fire, but don't send them
Used for local dev and CI tests.

## Testing

- Unit tests for `scrape.py` parsing run against `fixtures/sample_response.json`.
- Unit tests for `reconcile.py` use an in-memory SQLite and a series of crafted
  fixture states to exercise: new VIN, price drop, mileage drop, dealer change,
  vanish, reappear.
- Unit tests for `fairprice.py` use a synthetic listings table with known
  distributions.
- All tests run in CI on every push.

## Workflow (`.github/workflows/watch.yml`)

- Trigger: `cron: '*/30 * * * *'` (every 30 min) + `workflow_dispatch`
- Pin Python version explicitly (e.g., `python-version: '3.13.x'`)
- Pin all deps in `requirements.txt` with `==` (no `>=`)
- Steps: checkout, setup-python, pip install, run `python scrape.py && python reconcile.py`,
  commit changed files if any, push.
- Use `concurrency: { group: watch, cancel-in-progress: false }` to prevent overlap.
- A separate scheduled job for the Sunday digest.
- A separate scheduled job for nightly `fairprice.py` recomputation.

## Politeness

- User-Agent: `mb-wagon-watcher/1.0 (personal research; pwysocan@gmail.com)`
- Honor any `Retry-After` headers
- Single-threaded; no concurrent requests
- 30-minute polling is plenty; do not increase

## Cross-source price discrepancy detection (the Feb 11 lesson)

In Feb 2026, the same VIN was found listed at $72,995 on the Harlingen
dealer's own website and $69,995 on the official Mercedes-Benz USA CPO
portal. Same car, $3,000 spread, both pages live simultaneously. The
dealer cannot defend that gap because it's their own brand's inventory
system contradicting them — it is among the strongest pieces of pure
negotiation leverage I've ever seen.

The watcher should hunt for these automatically. For every active VIN
on the MBUSA portal:

1. Follow through to the dealer's own website listing for that VIN
   (the URL is typically linked from the MBUSA listing).
2. Scrape the price from the dealer site.
3. Compare to the MBUSA-portal price.
4. If the dealer-site price is higher by ≥$1,500 or ≥2%: **Tier 1
   alert**. The notification should include both prices, the spread
   in dollars and percent, and links to both pages.

Schema additions:
- `listings.mbusa_price` INTEGER
- `listings.dealer_site_price` INTEGER NULL  -- null if dealer-site fetch failed
- `listings.dealer_site_url` TEXT NULL
- `listings.dealer_site_checked_at` TIMESTAMP NULL
- `price_history`: include both prices on each row when both are known

Politeness:
- Dealer-site fetch happens only on first sight of a VIN and once per
  week thereafter, not on every 30-min poll. The MBUSA portal is the
  primary source.
- Use the same User-Agent. Honor robots.txt for each dealer domain
  (most dealer sites are permissive; some are not).
- If a dealer site requires JS rendering, fall back to extracting
  what you can from the initial HTML — don't fire up Playwright per
  dealer just for a price comparison. A best-effort fetch is fine;
  log failures and move on.

Failure mode: if dealer-site fetch fails, leave `dealer_site_price`
NULL and proceed. Don't block the run on a flaky dealer page.

## What "done" means

When I have bought a wagon, I archive the repo. Until then, this is a tool,
not a hobby. New features only get built if they help me make a buying decision
faster or more confidently.

## UI / Design

Any user-facing surface in this project — weekly digest markdown,
notification embeds, optional future dashboard — follows the same
aesthetic: **SBB as the structural foundation, ECAL contemporary
practice as the expressive layer.**

Swiss SBB is the gold reference for *what to do*: refined
information design, 80+ years of consistency, scannability at the
core. Contemporary ECAL practice is the reference for *how to do it
in 2026*: more typographic range, dark-mode native, asymmetry within
the grid, marginalia and metadata treated as first-class design
elements.

When in doubt about a design choice, ask both questions: *"how would
SBB show this?"* and *"how would an ECAL student make that feel
contemporary, not 1970s?"*

### What SBB contributes (the foundation)

- **Departure boards** as the model for data tables. Stacked, tight,
  monospaced; every pixel earning its keep.
- **The Hilfiker clock** (Hans Hilfiker, 1944) as the model for
  numerical display: black hands, white face, one red element that
  signals when something matters. Apple licensed it for a reason.
- **The SBB typeface** (B+P Swiss Typefaces, 2005) as the standard
  for information typography. Note: SBB itself replaced Helvetica
  with this custom face precisely because Helvetica was insufficient
  for modern wayfinding. Our type stack follows the same logic —
  see "Type stack" below.
- **The pictogram system** — any iconography follows: monochrome,
  hairline-weight, geometric.
- **Discipline over time.** SBB has resisted every fashionable
  redesign trend since the 1940s. That's the model.
- **SBB Red** (`#EB0000`) as the only accent color, used only as a
  signal.

### What contemporary ECAL practice contributes (the modern layer)

- **Wider typographic range.** SBB era = single typeface, two weights.
  Contemporary ECAL = a tight family but with full weight axis used
  intentionally — hairline weights for structure, heavy weights for
  emphasis, middle weights mostly avoided. The contrast is the
  expression.
- **Variable typography.** Use OpenType features deliberately —
  tabular figures (`tnum`) for data, oldstyle figures (`onum`) for
  prose, slashed zero (`zero`), contextual alternates (`calt`),
  stylistic sets (`ss01`+).
- **Dark-mode native.** Not an afterthought. The design works in both
  light and dark from day one. The Hilfiker clock is white-on-black
  at night and the digital descendant should be too.
- **Asymmetry within the grid.** Pure Swiss is often symmetric. ECAL
  contemporary work uses the grid as a discipline but breaks symmetry
  deliberately — a column shifts, a label hangs into the gutter, a
  number is set in a single oversized cell while everything else is
  tight.
- **Marginalia and metadata as design.** Timestamps, version numbers,
  trace IDs, source URLs — shown prominently in a side margin or
  footer, set in small mono, treated as part of the visual system,
  not hidden. The "raw" feeling. The watcher's run timestamps and
  dataset version belong here.
- **Footnote-style annotations.** Superscripted reference numbers
  (`Keyes¹`) linking to a dense, smaller-set notes block at the
  bottom of a section. The newspaper-of-record convention, applied
  to data.
- **Density paired with breath.** Pure SBB is uniformly dense.
  Contemporary work alternates: very large empty zones next to very
  packed zones. The contrast is what makes the dense zones legible.
- **Tactile-digital surfaces.** Treat the screen as a substrate the
  way print designers treat paper. Real margins. Gutters that feel
  like a bound book. Headers that act like running heads. Page
  numbers that act like page numbers.

### Type stack (modernized)

- **Primary sans:** `GT America`, `Söhne`, `PP Neue Montreal`,
  `ABC Diatype` (any of these are the contemporary Swiss-via-ECAL
  type stack — commercial faces, what you'd actually see in current
  ECAL student work). Fallback to `Inter` for free / open-source
  projects. Inter was specifically designed by Rasmus Andersson as
  a screen-optimized neo-grotesque — it does Helvetica's job better
  than Helvetica does.
- **Mono (data):** `JetBrains Mono`, `IBM Plex Mono`, `GT America Mono`.
- **Serif (rare, for editorial moments only):** if a serif is needed —
  e.g., a long-form note, a quoted dealer comment — use `GT Sectra`,
  `PP Editorial`, or fallback to `Tiempos`.
- **Do not use:** Helvetica, Helvetica Neue, or Arial. The
  Helvetica family is explicitly excluded — even SBB itself replaced
  it in 2005 because it failed at modern wayfinding tasks. Inter is
  the better default. Also avoid: any geometric humanist sans (DM
  Sans, Manrope), any workhorse-default sans (Roboto, Open Sans),
  any typeface from the Google Fonts top-50 except Inter and IBM Plex.

### Interaction primitives

**The VIN is the canonical identifier of a car in this system.** It
appears on every surface — dashboard tables, notification cards,
weekly digests, decision-log entries — and it is *always* rendered as
the primary clickable element, with the click target being the
dealer's listing URL for that VIN. The dealer name, photo, price
number, etc. are not links; only the VIN is.

This rule has three reasons behind it:

1. **Unambiguous semantics.** A VIN is unique, immutable, and
   already monospace-formatted. The user knows exactly what they're
   clicking; there's no question whether "Keyes European" links to
   the dealer's home page or to a specific listing.
2. **Cross-surface consistency.** The same 17-character string
   appears in every surface and behaves identically. After three
   weeks the user reads VINs the way pilots read tail numbers — as
   primary objects, not strings.
3. **Print compatibility.** When a digest is committed to git, the
   VIN is still readable as a unique reference even if the link
   target is dead. Dealers de-list cars; VINs persist forever.

Visual treatment of the VIN-link varies by surface density:

- **Notification cards:** permanent 1px underline (always visible).
  The card is sparse enough that the underline doesn't compete.
- **Dashboard table:** permanent 1px underline, with hover thickening
  to 2px. The dense format means the underline is one of the
  strongest visual elements; if it starts to feel too busy, drop to
  hover-revealed underline only.
- **Weekly digest:** GitHub auto-links bare URLs in markdown. Render
  the VIN as a markdown link `[W1KLH...](https://...)`. GitHub will
  apply its standard link styling.

When a VIN appears in prose ("compared to W1KLH6FB6SA153938"), it
remains a link. Never reproduce a VIN as plain text within the
project's surfaces.

**Weekly digest (`digest/YYYY-WW.md`):** numbered sections
(`## 01 — Headline counts`), em-dashes (`—`) and en-dashes (`–`)
used correctly, tabular alignment that renders cleanly on GitHub,
right-aligned numerics. Footnote-style annotations for dealer
notes. Metadata footer with run timestamp and snapshot ID.

**Notification embeds (Pushover):** strip to essentials.
Lead photo, single line of price + miles + dealer + percentile-rank.
SBB Red appears only for Tier 1 alerts.

**Future dashboard (Datasette / Streamlit / static HTML):** this is
where the modern layer fully expresses. Apply the full rule set.
Departure-board data tables; oversized headline numbers in display
weight; marginalia column for metadata; light/dark mode toggle that
respects system preference; asymmetric layout where it improves
scanning.

### Concrete CSS (SBB foundation, ECAL contemporary)

```css
:root {
  /* Light mode */
  --bg: #ffffff;
  --fg: #111111;
  --muted: #666666;
  --rule: #e5e5e5;
  --hairline: #00000010;       /* hairline rules with subtle alpha */
  --signal: #EB0000;            /* SBB Red — only as signal */

  --font-sans: 'GT America', 'Söhne', 'PP Neue Montreal', 'ABC Diatype', 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace;
  --font-serif: 'GT Sectra', 'Tiempos Text', Georgia, serif;

  --baseline: 8px;
  --gutter: 24px;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0a0a0a;             /* near-black, not pure */
    --fg: #f0ede8;             /* warm off-white */
    --muted: #888888;
    --rule: #222222;
    --hairline: #ffffff15;
    /* signal stays the same — SBB Red works in both modes */
  }
}

body {
  background: var(--bg);
  color: var(--fg);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.5;
  letter-spacing: -0.005em;
  font-feature-settings: "ss01", "cv11", "calt";
}

/* Display numerics — used for headline data (e.g. "53 wagons nationally") */
.display {
  font-family: var(--font-sans);
  font-weight: 100;            /* hairline — pair with heavy elsewhere */
  font-size: 96px;
  line-height: 1;
  letter-spacing: -0.04em;
  font-feature-settings: "tnum", "ss01";
}

/* Departure-board data table */
table.data {
  font-family: var(--font-mono);
  font-size: 12px;
  font-feature-settings: "tnum", "zero";  /* slashed zero */
  width: 100%;
  border-collapse: collapse;
}

table.data th {
  text-align: left;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 10px;
  font-weight: 500;
  color: var(--muted);
  border-bottom: 1px solid var(--fg);
  padding: 8px 0;
}

table.data td {
  padding: 6px 0;
  border-bottom: 1px solid var(--rule);
  vertical-align: baseline;
}

table.data td.num {
  text-align: right;
  font-feature-settings: "tnum", "zero";
}

/* Section markers — print-influenced */
.section-marker {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}

/* Marginalia / metadata — set small, in margin or footer */
.metadata {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--muted);
  font-feature-settings: "tnum";
}

/* Footnote references */
.footnote-ref {
  font-size: 0.7em;
  vertical-align: super;
  font-feature-settings: "sups";
  color: var(--muted);
}

/* Signal — the only red */
.signal { color: var(--signal); }
```

### Anti-patterns (don't do)

- **No additional accent colors.** No green for "good," no yellow
  for "caution." SBB Red and absence-of-red. Status differentiation
  comes from typography (weight, position, scale), not from a color
  palette.
- **No badges, pills, or chips.** Status is shown through
  typography or column position.
- **No rounded corners** on data containers. Hairlines and right
  angles only.
- **No drop shadows, gradients, or skeuomorphic textures.**
- **No middle-weight type for emphasis.** Pair hairline (100/200)
  with heavy (700/800). The middle (400/500) is for body text only.
- **No animation beyond state transitions.** The Hilfiker clock
  doesn't animate; neither does the dashboard.
- **No emoji.** Pictograms in the SBB tradition only, used at most
  once per view.
- **No hover effects beyond underline-on-link.**
- **No "Designed by" or version badges in the visible UI.** That
  metadata lives in the marginalia footer, set small.

## Build order (smallest viable slice first)

1. Schema + migrations in `db.py`. Tests for migration up/down.
2. `scrape.py` against the fixture only. No network yet.
3. `reconcile.py` with full diff logic, tested against synthetic fixtures.
4. Wire up the GitHub Action with health-check + commit-back. Run for 48 hours
   with notifications disabled to confirm stability.
5. `notify.py` — start with Tier 1 only, on a single channel.
6. `fairprice.py` + add column to schema.
7. VIN decode + geo enrichment.
8. Weekly digest.
9. Watchlist + Tier 2/3 notifications.
10. Cross-source price discrepancy detection (dealer-site vs MBUSA-portal).

Don't skip ahead. Each step needs to work before the next is built.
