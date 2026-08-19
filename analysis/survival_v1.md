# Survival analysis v1 — VIN lifetimes, spring/summer 2026 baseline

**Date:** 2026-07-30
**Data:** `data/inventory.db` (`listings`, `price_history` with price>0,
`notifications` gone/reappeared event trail), observations 2026-04-26 →
2026-07-30. Companion to [eom_pattern.md](eom_pattern.md).

> **Re-run reminder:** re-run against the September re-run of eom_pattern
> (after 2026-09-25) to compare summer vs fall market speed.

## Headline numbers

- **Clean cohort: 94 VINs** (first seen ≥ 2026-04-28; the 36-VIN baseline
  scrape of 2026-04-26 is excluded because their true listing start is
  unknown). 65 completed lifetimes ("sold"), 29 right-censored.
- **Median time to sale: 15 days** (Kaplan-Meier; IQR 6–43). A quarter of
  cars clear within 6 days; a quarter survive past 43.
- **Pricing at listing barely moves the median but strongly shapes the
  tail.** Cheap (<20th pct) median 13d vs expensive (>50th) 19d — but the
  expensive group's 75th percentile is 51 days vs 27–35 for the rest, and
  nearly all long-lived actives listed above the 50th percentile.
- **Linear elasticity is weak: ~1.1 fewer days per 10 percentile points
  cheaper (r² = 0.04) — effectively noise at the median.** The relationship
  is threshold/tail-shaped, not linear: among completed sales the median is
  10 days in *every* percentile band; what changes is the right tail
  (43–76-day sales and the still-active stale inventory are almost all
  >50th percentile listings).

## Data prep

1. **Reappearance cleaning.** A VIN that goes "gone" and reappears within
   14 days is one continuous listing. This is load-bearing: the MBUSA feed
   flaps VINs in and out constantly — **654 gone events across all VINs
   (507 within the cohort, touching 78 of 94 VINs) were reclassified as
   feed noise rather than sales**. Naively counting delistings as sales
   would overstate sales by ~10×. A VIN gone >14 days with no reappearance
   is treated as sold at its last observed price, dated at the gone event.
   The 13 cohort VINs currently gone ≤14 days are undetermined and
   censored at their gone date (not counted as sales).
2. **price=0 rows:** the 10 glitch rows of 2026-04-26T21:59:47Z were
   already deleted from `price_history` (commit 9c7f5b0); the analysis
   additionally filters `price > 0` throughout.
3. **Cohort restriction:** first_seen ≥ 2026-04-28 → **n = 94** of 130
   tracked VINs.
4. **Feed-flap price noise** (per the envelope method in eom_pattern.md,
   where raw deltas overcount real cuts 153 vs 117): all prices here are
   read as-of a date from the stabilized `price_history` series (latest
   row at or before the date), so intra-flap oscillation doesn't affect
   listed/final prices.

**Listed-price percentile** is computed as-of each VIN's first-seen date
against the pool active that day, using fairprice.py's tier/midrank method
(strict: year ±1, mileage ±15k; ≥5 comps; fall back loose/broad).
Coverage: 94/94 (80 strict, 7 loose, 7 broad).

## Kaplan-Meier: overall

S(t) for the full cohort (events at day t → survival after t):

| day | 1 | 3 | 5 | 7 | 10 | 15 | 20 | 26 | 35 | 43 | 51 | 65 | 76 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S | .90 | .83 | .75 | .69 | .57 | **.50** | .40 | .33 | .26 | .24 | .18 | .14 | .11 |

Median 15 days, quartiles 6 / 43. Note the front-loading: this matches
eom_pattern.md's finding that price cuts also front-load — the market's
whole tempo is set in the first three weeks.

## By fair-price percentile at listing (the key split)

| group | n | sold | median | q25 | q75 |
|---|---|---|---|---|---|
| <20th (aggressive) | 15 | 12 | **13d** | 4 | 35 |
| 20–50th (fair) | 41 | 28 | **14d** | 7 | 27 |
| >50th (expensive) | 38 | 25 | **19d** | 7 | 51 |

Aggressively-priced cars clear ~1.5× faster at the median, but the real
separation is in the tail: the >50th group holds essentially all of the
40+ day survivors (sold at 43/51/51/65/76 days, plus the current stale
actives at pct 65–96). Practical read: a well-priced watchlist match has
a ~2-week fuse; an overpriced one may hang around long enough to become a
stale-inventory negotiation target.

## By mileage tier (mileage at first sight)

| tier | n | sold | median | q25 | q75 |
|---|---|---|---|---|---|
| <7,500 mi | 23 | 16 | 14d | 7 | 43 |
| 7,500–15,000 | 20 | 14 | 18d | 10 | 51 |
| >15,000 | 51 | 35 | 13d | 4 | 35 |

No strong mileage effect; high-mileage cars clear marginally fastest
(they're also the cheapest in absolute terms). Small n per cell — don't
over-read the 7.5–15k slowness.

## Elasticity summary

OLS on completed sales only (n=65): days = 9.1 + 0.113 × pct, r² = 0.036.
**One-liner: each 10 percentile points cheaper ≈ 1.1 fewer days on market —
too weak to be actionable; the relationship is nonlinear.** Median sold-days
is 10 in every percentile band; percentile predicts *whether a car risks
becoming stale* (the >50th tail), not *how fast a typical car sells*.
(Sold-only regression also understates the true effect — the censored
long-lived actives, excluded here, skew expensive.)

## Watchlist subset (2024+, ≤15k mi — the criteria.md spec)

All 24 completed lifetimes, sorted by days on market:

| VIN | dealer | listed → final | days | pct@list | mi | yr |
|---|---|---|---|---|---|---|
| W1KLH6FBXSA153487 | MB Wilmington | $69,900 → $69,900 | 0 | 23 | 9,149 | 2025 |
| W1KLH6FB2TA196545 | MB Madison | $86,332 → $86,332 | 0 | 96 | 5,669 | 2026 |
| W1KLH6FB8SA137367 | Euro Motorcars | $64,680 → $64,680 | 1 | 3 | 7,718 | 2025 |
| W1KLH6FB2SA106048 | RBM Atlanta | $73,779 → $73,779 | 1 | 47 | 9,191 | 2025 |
| W1KLH6FB2SA127188 | MB Fort Pierce | $69,998 → $69,998 | 2 | 32 | 6,963 | 2025 |
| W1KLH6FB6TA212925 | MB Massapequa | $87,350 → $87,350 | 3 | 96 | 6,474 | 2026 |
| W1KLH6FB5SA085731 | MB Morristown | $66,985 → $66,985 | 5 | 9 | 2,445 | 2025 |
| W1KLH6FB2SA155265 | MB Union | $76,390 → $76,390 | 5 | 62 | 2,526 | 2025 |
| W1KLH6FB7SA147419 | MB Springfield | $75,481 → $75,481 | 7 | 66 | 3,515 | 2025 |
| W1KLH6FBXSA138665 | MB Kansas City S | $73,990 → $73,990 | 9 | 66 | 5,562 | 2025 |
| W1KLH6FB2RA026291 | Autohaus On Edens | $79,984 → $79,984 | 10 | 96 | 14,012 | 2024 |
| W1KLH6FB1SA114903 | MB Wichita | $73,998 → $73,598 | 10 | 56 | 7,394 | 2025 |
| W1KLH6FBXSA104094 | MB Jacksonville | $74,998 → $74,891 | 10 | 61 | 7,136 | 2025 |
| W1KLH6FBXSA142568 | MB Rochester | $68,995 → $69,995 | 12 | 22 | 8,490 | 2025 |
| W1KLH6FBXSA087524 | RBM Alpharetta | $73,984 → $73,984 | 14 | 50 | 6,546 | 2025 |
| W1KLH6FB2SA151507 | Sun Motor Cars | $75,489 → $75,489 | 15 | 77 | 12,945 | 2025 |
| W1KLH6FB3SA096615 | MB Sarasota | $74,489 → $74,374 | 18 | 65 | 1,568 | 2025 |
| W1KLH6FB2SA109290 | MB Fort Pierce | $67,998 → $65,995 | 18 | 7 | 12,383 | 2025 |
| W1KLH6FB7SA154743 | EuroMotorcars Devon | $73,681 → $73,681 | 21 | 41 | 6,176 | 2025 |
| W1KLH6FB0TA237464 | MB Charleston | $80,794 → $79,999 | 43 | 92 | 4,467 | 2026 |
| W1KLH6FB6RA026150 | MB Burlington | $72,998 → $72,492 | 51 | 64 | 12,992 | 2024 |
| W1KLH6FB6SA138629 | MB Kingsport | $82,564 → $74,531 | 51 | 98 | 2,866 | 2025 |
| W1KLH6FB0SA088150 | RBM Alpharetta | $73,984 → $72,460 | 65 | 60 | 8,522 | 2025 |
| W1KLH6FBXRA058115 | MB Centerville | $71,860 → $70,937 | 76 | 58 | 8,958 | 2024 |

Pattern check within the watchlist: the four cars that listed under the
25th percentile AND under $70k (Wilmington, Euro Motorcars, Fort Pierce
×2, Morristown) all cleared in ≤18 days, most in ≤5. Every 40+ day
survivor listed above the 55th percentile. The two clearing-band sales
(Euro Motorcars $64,680, Fort Pierce $67,998 → $65,995) reinforce
MARKET_NOTES' $65,980–$67,998 clearing band.

Censored watchlist VINs still on market (12): notably RBM Atlanta
W1KLH6FB3RA004560 (55d, $74,984 → $72,368, pct 75), Critz
W1KLH6FB8TA215339 (46d, $76,491 → $71,795), Pompano W1KLH6FB0TA220597
(36d, $78,491 → $74,995), Bud Smail W1KLH6FB5TA256561 (22d, $85,965 →
$77,991) — all listed pct ≥65, all now multi-cut. These are the
stale-inventory targets the November playbook depends on.

## Caveats

- **Right-censoring:** 29/94 lifetimes are incomplete (16 still listed,
  13 gone ≤14 days and undetermined). Long-lived actives — mostly
  expensive listings — are exactly the ones censoring truncates, so
  group differences in the tail are *understated*, and the sold-only
  elasticity regression is biased toward zero.
- **Summer-market bias:** this window is May–July. Fall dynamics (model-
  year changeover, November close pressure) may differ — compare against
  the September re-run before using these medians for November planning.
- **"Sold" = delisted >14 days at last observed price.** We observe
  disappearance from the feed, not transactions. Dealer trades, auction
  pulls, and feed eligibility changes all look like sales; actual
  transaction prices may sit below the last asking price.
- **Very short lifetimes (0–3 days) may be feed artifacts** — a car can
  appear in the union scrape once and never re-qualify (e.g. Madison's
  $86,332 2026 "selling" in 0 days at the 96th percentile is more
  plausibly a feed blip than a sale). They pull the overall median down.
- The 14-day merge threshold is a judgment call; at the observed flap
  cadence (most reappearances within 1–3 days) the results are not
  sensitive to ±a few days.

## Data-integrity caveat added 2026-08-19 (read before reusing these numbers)

A pagination bug found on 2026-08-19 means the pool this analysis ran on
was systematically truncated: `scrape.fetch_all()` pinned `start=1`, which
is **page 1**, so the 12 nearest-to-90210 listings (page 0) were never
fetched for the life of the project. Fixed in scrape.py; see
fixtures/endpoint_notes.md "Pagination".

Concrete effects on this analysis:

- **Pool sizes and medians are computed on a truncated, distance-biased
  sample.** Page 0 is the *nearest* inventory, which on 2026-08-19 included
  two CA cars at 71.8 mi listing for $41,453 and $46,871 — well below the
  band this analysis calls the market. 6 of the 23 VINs live that day had
  never entered the DB at all.
- **Some "sales" are artifacts.** A car that slid from page 1 into page 0
  as the pool shrank vanished from the watcher's view while still being
  listed, and the >14-day rule then scored it as sold. On 2026-08-19, 3
  VINs marked `gone` were live in the feed (2 of them inside this
  analysis's clean cohort), so the sold/censored split and the lifetimes
  of affected VINs are wrong in the "too short" direction.

Treat the *shape* findings (front-loading, percentile-track separation) as
provisional but plausible — they don't depend on the missing page — and
treat any absolute level (pool size, median asking, clearing band, count of
sales) as unreliable until the v2 re-run on post-fix data.
