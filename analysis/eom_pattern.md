# EOM drop clustering & per-VIN decay curves — price_history validation

**Date:** 2026-07-30
**Data:** `data/inventory.db` `price_history` (450 rows, 2026-04-26 → 2026-07-30)
joined to `listings` for `first_seen` / dealer. Validates the two hypotheses
deferred from the 2026-07-30 analysis session (see MARKET_NOTES.md entry of
that date): month-end drop clustering and day 25–35 / 55–65 / 85+ decay
clustering.

> **Re-run reminder:** re-run this analysis after **2026-09-25**, when the
> late-DoL bins (55–65, 66–84, 85+) will have enough uncensored data to
> confirm or refute the absence of late-life cut clusters (verdict 2's
> right-censoring caveat).

## Verdicts up front

1. **Month-end clustering: PARTIALLY HELD.** There is a real but modest
   *frequency* bump concentrated on days 28–30 (~1.83 envelope drops/day vs
   1.16 baseline, +58%), and day 29 is the single hottest late-month day
   (2.5/day). But there is **no magnitude effect** — mean cut at EOM is
   *smaller* than baseline ($927 vs $1,088), per-calendar-day aggregate is
   flat ($1,191 vs $1,261) — days 26–27 are *below* baseline, and mid-month
   days 13 / 17 / 18 spike just as hard (2.3–3.0/day). The digest-movers
   "4-for-4" read picked up a real day-28–30 frequency effect, but it is not
   distinctive enough to be load-bearing for November timing on its own.
2. **Decay clustering at day 25–35 / 55–65 / 85+: DID NOT HOLD.** Cut hazard
   declines monotonically from listing — drops front-load in the first
   ~3 weeks and thin out. The 25–35 band is active only as the tail of that
   decline, not a distinct cluster; 55–65 and 85+ are nearly empty. Mean cut
   size is flat (~1.5%) across successive cuts, i.e. "each cut larger than
   the last" is not supported on average (later-cut-bigger holds in only
   43 of 66 successive pairs, with flat means). Individual escalators exist
   (Critz d33 −4.0%, Huntington d45 −6.2%) but they are exceptions.

## Methodology

- Per VIN, order `price_history` by `observed_at`, collapse consecutive
  duplicate prices.
- **Raw drops** = consecutive-row delta < 0. Noisy: the feed flaps between
  two prices for days (e.g. W1KZH6AB1PB178619 oscillated $62,406 ↔ $61,275
  across 2026-07-01…07-04), producing spurious repeated drops.
- **Envelope drops** (headline metric) = price falls below the VIN's prior
  running minimum; size = prev_min − new_min. Immune to flapping; counts
  each real cut once.
- **Excluded:** 10 rows with `price = 0`, all stamped 2026-04-26T21:59:47Z —
  a scrape glitch on the first observation day. Left in, they add a fake
  $661k of "drops" on day 26 and would have manufactured exactly the
  month-end signal under test. (Data-quality follow-up: consider deleting
  these rows or guarding the scraper against price=0.)
- **Day-of-month test:** days 26–31 (EOM) vs days 5–25 (baseline); days 1–4
  excluded as month-boundary spillover. Rates normalized by how many
  calendar days of each class fall in the window (EOM 21, baseline 63,
  excluded 12).
- **Decay curves:** days-on-lot = `observed_at` − `listings.first_seen` at
  each envelope drop; cut % of prior envelope price; binned.

## Day-of-month results (117 envelope drops / 153 raw)

| class | envelope n | drops/day | mean cut | agg $/cal-day |
|---|---|---|---|---|
| EOM (26–31) | 27 | 1.29 | $927 | $1,191 |
| baseline (5–25) | 73 | 1.16 | $1,088 | $1,261 |
| excluded (1–4) | 17 | 1.42 | $787 | $1,115 |

Raw drops show the frequency effect more strongly (2.14 vs 1.32/day, +63%)
with the same absent magnitude effect ($826 vs $1,164 mean cut).

Hot days by envelope-drop rate (occurrences in window in parens):
day 13 → 3.0/day (9 drops/3), day 29 → 2.5/day (10/4), day 17 → 2.7/day
(8/3), day 18 → 2.3/day (7/3), days 28–30 combined → 1.83/day (22/12).
Days 26–27 → 0.63/day (5/8), *below* baseline.

## Decay results (envelope drops by days-on-lot)

| DoL bin | n | drops per day-of-width | mean cut % |
|---|---|---|---|
| 0–14 | 53 | 3.53 | 1.41% |
| 15–24 | 28 | 2.80 | 1.60% |
| 25–35 | 20 | 1.82 | 1.51% |
| 36–44 | 7 | 0.78 | 0.94% |
| 45–54 | 2 | 0.20 | 3.56% |
| 55–65 | 5 | 0.45 | 1.46% |
| 66–84 | 1 | 0.05 | 1.75% |
| 85+ | 1 | 0.03 | 1.31% |

Successive-cut sizes by ordinal: #1 1.53%, #2 1.55%, #3 1.59%, #4+ 1.28% —
flat, not escalating.

**Censoring caveats, both directions.** 36 of 130 VINs were already listed
when the watcher started (2026-04-26), so their true days-on-lot is
understated — this is where the "91 DoL" style figures for Hampton /
RBM Atlanta come from and they cannot anchor the late bins. Restricting to
the 94 uncensored VINs preserves the front-loaded shape (35 / 19 / 17 drops
in the first three bins, then ≤4). Conversely the 3-month window
right-censors late bins — few uncensored cars *can* be 55+ days old yet —
so "no late clusters" is *unconfirmed absence*, not proof. Re-run this
after another 60–90 days of data before hardening the November entry-point
model ("2–3 cuts deep by late November" survives — multi-cut VINs are real —
but the cuts arrive earlier and flatter than the clustered model assumed).

## Data-integrity caveat added 2026-08-19 (read before reusing these numbers)

A pagination bug found on 2026-08-19 means the pool this analysis ran on was
systematically truncated: `scrape.fetch_all()` pinned `start=1`, which is
**page 1**, so the 12 nearest-to-90210 listings (page 0) were never fetched
for the life of the project. Fixed in scrape.py; see
fixtures/endpoint_notes.md "Pagination".

Effects specific to this analysis:

- **The drop census is incomplete, not just small.** Price cuts on page-0
  cars were never recorded, so both the day-of-month counts and the
  days-on-lot bins are built from a distance-biased subset of the market.
  6 of the 23 VINs live on 2026-08-19 had never entered the DB at all.
- **Some days-on-lot values are wrong.** A car that slid between pages
  disappeared and re-entered the feed as far as the watcher could tell;
  where that produced a new `first_seen`, its days-on-lot restarts from
  zero, which biases drops toward the early bins — the same direction as
  this analysis's headline "cuts front-load" finding.

The month-end verdict (a day-28–30 frequency bump with no magnitude effect)
rests on within-sample comparisons and is unlikely to flip. The decay-bin
verdict is the one to re-test: its "no late clusters" conclusion was already
flagged as unconfirmed absence due to right-censoring, and page-0 truncation
pushes the same way. Fold both into the v2 re-run after 2026-09-25 on
post-fix data.
