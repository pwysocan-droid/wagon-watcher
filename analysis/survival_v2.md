# Survival v2 + post-fix band recheck — fall 2026

**Date:** 2026-10-15
**Data:** `data/inventory.db` up to the 2026-10-15T12:57Z run. The script
that produces every number below is [survival_v2.py](survival_v2.py).
Companion to [survival_v1.md](survival_v1.md) and
[eom_pattern.md](eom_pattern.md). Buying criteria per
[criteria.md](../criteria.md).

## Verdicts up front

1. **Cars are selling more slowly this fall.** The v2 Kaplan-Meier median
   time to sale is **21 days** (q25 = 12; q75 not reached), against 15–16
   in v1. Only 33% of v2 cars were gone within 14 days, against 49–52% in
   v1. For S214 2024+ cars it was **20% against 44%**.
2. **v1's speed was mostly real, not a truncation artifact.** Dropping the
   24 `suspect_sale` VINs only moves v1's 14-day exit share from 52% to
   49%. The truncation inflated the sale count, but it doesn't explain the
   gap to fall.
3. **The clearing band survives.** The only two post-fix qualifying sales
   under $70k closed at **$66,590 and $67,600**, both inside the spring
   band of $65,980–$67,998. No qualifying car has sold below the band
   since July.
4. **The November supply forecast doesn't survive.** At the $67,000 cap
   (after allowing for shipping), post-fix inflow is 1 car in 57 days.
   - Expected count for Oct 15 – Nov 30: **0.8**, with a 90% CI of
     0.04–3.8.
   - Probability of **zero qualifying listings: 45%.**
   - Pooling all non-baseline months gives 1.1 expected (90% CI 0.4–2.5)
     and P(0) = 34%.
   - The July forecast of 3–5 candidates is off by a factor of about 4.

## Methodology

Same as v1 unless noted.

- **Cohort:** VINs first seen on or after 2026-08-20. That's n = 61:
  34 S214 (2024+) and 27 S213 (2023 and earlier).
- **Sales and censoring:** I used each VIN's first lifetime.
  - A gone event followed by a reappearance within 14 days is merged as
    feed noise.
  - A VIN gone more than 14 days counts as sold at its gone date, at the
    last price observed.
  - A VIN gone 14 days or less before the cutoff is censored at its gone
    date. A VIN still listed is censored at the cutoff (2026-10-15 12:57Z).
- **Prices:** `price_history` rows with price over $1,000. Cuts use the
  envelope method from eom_pattern.md.
- **Percentile at listing:** fairprice.py's tiers and midrank method,
  computed as of first_seen against the pool listed at that moment.
  Coverage was 61/61 (50 strict, 9 loose, 2 broad).
- **Checking the code against v1:** run against v1's cohort and cutoff
  (first seen on or after Apr 28, cutoff Jul 31), it gives n = 94, 65
  sold, median 16, IQR 6–43. v1 published n = 94, 65 sold, median 15, IQR
  6–43. The one-day difference in the median comes from day-boundary
  rounding.

## 1. Kaplan-Meier, v2 cohort

**n = 61. 20 completed lifetimes and 41 censored (67%):** 24 still
listed, 17 gone 14 days or less and not yet decided.

| day | 1 | 3 | 7 | 10 | 14 | 21 | 28 | 35 | 43 |
|---|---|---|---|---|---|---|---|---|---|
| S v2 | .98 | .93 | .85 | .83 | .68 | **.48** | .48 | .34 | .34 |
| S v1 (as published) | .90 | .83 | .69 | .57 | ~.51 | .40 | .33 | .26 | .24 |

Median 21 days, q25 12, q75 not reached. The curve sits above v1's at
every horizon. The biggest gap is in the first 10 days: 17% of v2 cars
were gone by day 10, against 43% in v1.

**By percentile at listing:**

| group | n | sold | median | q25 | q75 |
|---|---|---|---|---|---|
| <20th | 10 | 6 | **16d** | 11 | 29 |
| 20–50th | 27 | 10 | **21d** | 11 | — |
| >50th | 24 | 4 | **not reached** | 15 | — |

**By generation:** S214 (2024+) has n = 34, 10 sold, median **29d**.
S213 (2023 and earlier) has n = 27, 10 sold, median 18d. The cars Paul is
shopping for are selling the slowest.

**Price cuts (envelope method):** 27 cuts on 20 of the 61 VINs. The
median first cut comes on day 9, and 17 of the 27 cuts fall within the
first 14 days. The mean cut is **2.1%**, against about 1.5% in v1. The
day 25–35 bin has only n = 3, so its 5.0% mean is noise.

## 2. Tempo comparison with matched exposure

This is the share of VINs sold within 14 and 21 days of first being seen.
Only VINs with at least 21 days of possible exposure plus 14 days to
confirm the sale are included (first_seen + 35 days ≤ cutoff). The v1
cohort uses pre-fix data up to 2026-08-18.

| cohort | n | sold ≤14d | sold ≤21d |
|---|---|---|---|
| (a) v1, excluding suspect_sale VINs | 67 | 49% | 63% |
| (b) v1, including suspect_sale | 84 | 52% | 65% |
| (c) v2 | 18 | **33%** | 61% |
| (a') v1 excluding suspect, S214 only | 34 | 44% | 62% |
| (c') v2, S214 only | 10 | **20%** | **40%** |

What the table shows:

- **Truncation barely matters here.** The gap between (a) and (b) is 3
  points. The `suspect_sale` artifacts added to v1's sale count, but they
  aren't why v1 looks faster.
- **Fall is slower in the first two weeks.** The 14-day exit share drops
  from about 50% to 33%. Across all v2 cars it catches up by day 21. For
  S214 cars it doesn't: 40% at 21 days against 62% in v1.
- **Small samples.** v2 has n = 18, or n = 10 for S214, because most of
  the cohort hasn't had 35 days yet. The direction is consistent across
  every cut of the data, but the size of the gap is uncertain. Re-run in
  mid-November with about 40 eligible VINs.

**Hindsight check on v1.** 5 of the v1 cohort's "sales" later reappeared
after gaps of more than 14 days, so they weren't sales:
- W1KLH6FB1SA114903, Wichita → Hoffman Estates (see §5)
- W1KLH6FB2TA196545, the 0-day "sale" at Madison that v1 already flagged
- W1KLH6FB0TA237464, Charleston
- W1KLH6FB7SA087237
- W1KZH6AB4PB180428

Dealer-to-dealer moves look exactly like sales in this feed.

## 3. Clearing band recheck, post-fix only

These are the qualifying cars (2024+, 15k miles or less at first seen)
whose lifetime ended on or after 2026-08-19. The rows marked v2 are in
the v2 cohort. Earlier first-seen dates are listed further below for
context.

| VIN | yr | mi | dealer | days | list → final | pct@list | vs band |
|---|---|---|---|---|---|---|---|
| …084620 | 2025 | 6,505 | Valley Imports, ND | 29 | 69,048 → **66,590** | 8 | **in band** |
| …084433 | 2025 | 4,029 | MB Madison, WI | 16 | **67,600** | 5 | **in band** |
| …104758 | 2025 | 9,077 | MB Rochester, NY | 10 | 70,578 | 28 | above |
| …105624 | 2025 | 2,680 | MB Columbus North, OH | 29 | 72,158 → 71,290 | 23 | above |
| …086396 | 2025 | 7,543 | MB Lynnfield, MA | 0 | 72,497 | 34 | above (0-day, possibly not a real sale) |
| …026171 | 2024 | 7,704 | MB Union, NJ | 13 | 76,995 | 77 | above |
| …004555 | 2024 | 5,868 | MB Alexandria, VA | 2 | 78,639 | 88 | above (2-day, possibly not a real sale) |
| …255810 | 2026 | 450 | MB Hilton Head, SC | 2 | 83,584 | 86 | above (2-day, possibly not a real sale) |

**The bottom of the band holds.** Both sales under $70k closed inside
$65,980–$67,998, and both were listed at the 5th–8th percentile.
- Madison sold at its list price.
- Valley Imports needed 29 days and two cuts. That's slower than v1's rule
  that every car under the 25th percentile and under $70k cleared within
  18 days.
- Nothing sold below $65,980 after the fix. The last qualifying car to
  ask less than that was Euro Motorcars at $64,680 on Jul 1.

**Sales outside the v2 cohort.** 11 more qualifying cars that were first
seen before Aug 20 ended their lifetimes between Aug 19 and Sep 15. All
of them were priced at $69,497 or more, mostly long-stale stock:
- RBM Atlanta ×2, final prices $71,973 and $71,591, after 121 and 102
  days
- Pompano, $75,491
- Bud Smail, $77,492
- Union ×2, $76,995 each
- Princeton, $80,999

Six of them "sold" between Aug 26 and 28. That's just before the scraper
degraded (see caveats), so some may be exits caused by the scraper rather
than real sales. They tell us where stale stock ends up, not what a
qualifying car should cost.

## 4. Qualifying inflow at the $67,000 cap (after shipping)

This counts listings that were 2024+, had 15k miles or less at first
seen, and ever asked **$67,000 or less**. Each car is counted in the
month it was first seen.

| month | count | cars | pre/post fix |
|---|---|---|---|
| Apr (baseline, already listed) | 5 | Chicago 61,516 · Critz 63,915 · Sycamore 65,491 · Cary 65,980 · Okemos 66,500 | pre |
| May | 2 | Fort Pierce 65,995 · Morristown 66,985 | pre |
| Jun | 0 | — | pre |
| Jul | 1 | Euro Motorcars 64,680 | pre |
| Aug | 1 | Valley Imports 66,590 (Aug 26) | post |
| Sep | 0 | — (Madison's $67,600 misses the $67k cap) | post |
| Oct 1–15 | 0 | — | post |

**Forecast for Oct 15 – Nov 30 (46 days).** Exact Poisson CI, 90%:

| rate basis | k / days | expected | 90% CI | P(0) | P(≥2) |
|---|---|---|---|---|---|
| post-fix (Aug 19 – Oct 15) | 1 / 57 | **0.80** | 0.04–3.81 | **45%** | 19% |
| pre-fix (Apr 28 – Aug 18) | 3 / 113 | 1.22 | 0.33–3.16 | 29% | 35% |
| all non-baseline | 4 / 171 | 1.08 | 0.37–2.47 | 34% | 29% |

The pre-fix rate is roughly comparable. On the day of the fix, page 0
held mostly cheap S213 cars, but a missed qualifier before then can't be
ruled out, so treat the pre-fix rate as a lower bound. Even so, every way
of measuring the rate gives about one candidate at most.
Nothing indicates the rate is rising into fall: only 2 new 2025s were
listed between Oct 1 and Oct 15.

## 5. Decision queue

- **W1KLH6FB1SA114903, Hoffman Estates.** Added to
  `config/decision_queue.json`:
  - Status: verification requested.
  - Target close $66,000–66,500, walk away at $67,000.
  - Price call window: Oct 28–30.
- **History annotated** in `config/vin_annotations.json`:
  - Listed at MB Wichita on Jun 17 for $73,998 with 7,394 miles.
  - Gone Jun 28 (v1 counted that as a sale).
  - Reappeared Aug 28 at MB Hoffman Estates for $68,999 with 8,755 miles,
    1,361 more than in Wichita.
  - Unchanged since then. 8,802 miles at last observation.
  - Strict percentile 4.

## Caveats

- **67% of v2 is censored.** The median rests on 20 completed lifetimes,
  so q75 and the >50th-percentile median can't be estimated yet.
- **Scraper cadence dropped.** watch.yml fires every 30 minutes, but
  since about Aug 27 only **3–7 runs a day** have landed. Before that it
  was 30–40. GitHub is dropping scheduled runs, and the heartbeat monitor
  added on Aug 28 is the visible response.
  - Fewer polls mean coarser timing for gone events and fewer brief flaps
    observed. The 14-day merge window is much wider than the gap between
    polls, so the classification of sales should be robust.
  - Aug 27 – Sep 3 was the worst stretch, with pools of 12–15 cars,
    likely only page 0. Gone events that cluster around it (several
    Aug 26–28 "sales" above) are the least trustworthy.
- **Possible API cap.** Recent runs return 28–33 listings, and the
  2026-10-15 digest flags five runs under 30. If the far edge of the pool
  is being cut off, some of the "sales" there are artifacts again, now at
  the far end instead of the near end.
- **"Sold" still means "disappeared from the feed."** The hindsight check
  found 5 reappearances among v1's sales. Treat any single sale with
  caution, especially 0–3 day lifetimes.
- **Season and pool make-up are mixed together.** The post-fix pool now
  includes the nearest cars, including LA, which the v1 pool never saw. A
  slower fall could partly reflect a different mix of cars. The S214-only
  rows control for generation but not for geography.

## Next re-run

Re-run around **2026-11-15**. By then about 40 v2 VINs will have 35 or
more days of exposure, and the >50th-percentile tail will start to have
completions. If the scraper cadence still hasn't recovered, fix it first.
