# MARKET_NOTES

Running market observations for the wagon watch. Newest entries on top.
Convention per entry: dated section header, observation → interpretation
structure, pattern signals marked with confidence.

## Endgame manual layer (Oct 15 – Nov 30)

The MBUSA CPO feed shows only cars already certified in MBUSA's system.
analysis/api_cap_probe.md confirmed it isn't capped, but it can't see
non-certified cars at Mercedes dealers, and that's where the in-band cars
are (Youngstown $60,778, Georgetown $62,999). For the buying window, the
watcher works as an alert system and `config/decision_queue.json` is the
case file. Three manual routines fill the gap.

**1. Weekly 15-minute sweep (Mondays).**
- Search CarGurus and Autotrader (plus Cars.com, which worked for these
  searches when others blocked) for 2024–25 E450 All-Terrains with 15k mi
  or less, nationwide, sorted by price.
- Focus on non-CPO cars at Mercedes dealers. That's the certifiable pool
  the feed can't see.
- For each hit under about $67k: capture the VIN, price history, dealer,
  and any "certified" claim in the seller notes. Then add it to
  `decision_queue.json` with `"source": "manual"` and next_action "call:
  mileage, Carfax, will you certify as part of the sale".
- Also check off-feed cars already in the queue for price changes. Cars.com
  detail pages show full price history.

**2. MB LA batch-cut watch (from Oct 29).**
- Every 2–3 days, check W1KLH6FB3TA212378 on CarGurus for a real price
  change, ignoring the $74,900 ↔ $75,081 fee flapping. CarGurus' per-listing
  JSON (`detailListingJson.action?inventoryListing=460915753`) has the
  history.
- The trigger is an *observed* cut, not a calendar date. Within 48h of the
  first cut, call and restate the standing written offer.
- Cuts come in lot-wide sweeps, so a cut on other MB LA CPO cars the same
  week is the early warning.

**3. Log every call the same day.**
- Write each call into the candidate's `call_log` in
  `config/decision_queue.json` **and** into `dealers.md`.
- Record:
  - who you spoke to
  - every number quoted (price, out-the-door, trade, fees, add-ons)
  - documents promised and by when
  - red flags (non-optional add-ons, "market adjustment", reluctance to
    send the CPO sheet or in-service date)
- Spoken details fade within about 48 hours. "You quoted $X on date Y" is
  leverage only if it's written down, ideally in an email back to the
  dealer that confirms it.

## 2026-10-15 — Survival v2 on post-fix data: fall is slower, the band holds, supply forecast dies

Source: analysis/survival_v2.md (61-VIN post-fix cohort, first seen on or
after 2026-08-20; 20 completed lifetimes, 67% censored), developed with
the claude.ai session of 2026-10-15.

**What survives from v1**

- **The clearing band, $65,980–$67,998 (high confidence).** Both post-fix
  qualifying sales under $70k closed inside it: Valley Imports at $66,590
  and Madison at $67,600. Nothing has sold below the band since July. The
  survivorship-bias warning still applies: ignore the pool median.
- **Percentile at listing predicts the car's path (high confidence,
  stronger than before).** Medians: under the 20th percentile 16 days,
  20th–50th 21 days, over the 50th not reached (4 of 24 sold). Expensive
  listings still become the stale stock.
- **Cuts come early (moderate confidence).** The median first cut is on
  day 9, and 17 of 27 cuts land in the first 14 days. Cuts are a bit
  bigger than v1 found: 2.1% on average, against about 1.5%.
- **v1's speed was mostly real.** Excluding the 24 `suspect_sale` VINs
  moves v1's 14-day exit share only from 52% to 49%. Page-0 truncation
  inflated the sale count but didn't create the fast tempo.

**What dies**

- **"Engage week one, decide by day 10–14."** The v2 median is 21 days.
  Only 33% of cars were gone by day 14, against about 50% in v1. For S214
  2024+ cars it was 20% against 44%, and the S214 median is 29 days.
  Revised: the fuse is about 3 weeks. Engage early still, but day 10–14 is
  no longer a hard deadline. (Moderate confidence: only n = 18 cars, or
  10 for S214, had enough time to be compared.)
- **"Under the 25th percentile and under $70k clears in 18 days or
  less."** Valley Imports was listed at the 8th percentile and took 29
  days and two cuts. Low-percentile cars still sell, just not always
  fast.
- **The November arithmetic (3–5 qualifying candidates).** At the $67,000
  cap after shipping, post-fix inflow is 1 car in 57 days.
  - Expected for Oct 15 – Nov 30: **0.8** (90% CI 0.04–3.8). **P(zero) =
    45%.**
  - Pooled across all months: 1.1 expected, P(0) = 34%.
  - The July projection of qualifying cars listing at $63.5–66.5k also has
    no post-fix support. No qualifying car has asked below $66,590 since
    Jul 1.

**What it means for November.** Don't wait for a new listing to show up
in the window. There's a one-in-three to one-in-two chance none does.
The realistic paths are:
1. Negotiate an existing car down into the band. Hoffman Estates is now
   in the decision queue: target $66,000–66,500, walk away at $67,000,
   call Oct 28–30.
2. Loosen a constraint. MB Los Angeles 2026 at $74,900 is local; on
   mileage, Barrington 2025 is at $62,500 with 23k miles.

**Process warnings.** Since about Aug 27 only 3–7 scrape runs a day have
landed, against 30–40 before, because GitHub is dropping scheduled runs.
The API may also be capping results at about 30 listings. Both make gone
events noisier. Re-run v2 around 2026-11-15, after fixing the scrape
cadence. The month-end effect was not retested in this pass.

## 2026-07-31 — Survival analysis v1: reaction windows and percentile tracks

Strategic conclusions from analysis/survival_v1.md (94-VIN clean cohort,
65 completed lifetimes), developed in the claude.ai session of 2026-07-31.

**1. The reaction window is ~2 weeks, not hours (pattern signal, high
confidence).** Median time-to-sale is 15 days (KM, IQR 6–43). Well-priced
qualifying cars carry a 13–18 day fuse. The Keyes flash-sale (gone in
hours) is the exception, not the rule. Practical implication: when a
qualifying car appears, there is time for the full remote-purchase
guardrail sequence (Carfax + AutoCheck, CPO sheet, video walkaround, PPI)
— but not for passive watching. Engage week one, decide by day 10–14.

**2. Percentile-at-listing predicts the car's track, not its speed
(pattern signal, high confidence).** Sold cars cluster ~10 days in every
price band (elasticity r²=0.04, ~1.1 days per 10 percentile points). But
the tail separates hard: every 40+ day survivor listed above the 55th
percentile; everything under the 25th percentile and under $70k cleared
in ≤18 days. Triage rule for November:
- <25th percentile: Fort Pierce archetype. List price is the deal.
  Engage immediately, decide fast.
- 25th–55th: conventional negotiation band.
- >55th percentile: near-certain future stale target. Don't chase now —
  calendar it and phone-negotiate at day 45+.

**3. Two-track refinement.** The "let fresh arrivals run their cuts,
engage as cuts flatten (~week 3)" play only applies to mid/high-percentile
cars — low-percentile cars sell before their cuts flatten. Waiting out a
low-percentile car means losing it.

**4. November window arithmetic.** A 15-day median lifetime means the
Oct 15–Nov 30 window spans ~3 full market turnover cycles. At summer
inflow rates (~5–7 new listings/week) that's 30+ listings crossing the
window; historical criteria conversion (~10–15%) puts the base case at
3–5 qualifying candidates even without fall replenishment.

Validation reference: analysis/survival_v1.md. Re-run as survival_v2 at
the late-September checkpoint; diff the two for the seasonal tempo
reading (did the market slow down or speed up into fall?).

## 2026-07-30 — 101-day analysis: survivorship bias, decay clustering, month-end 4-for-4

Three findings from the April 29 – July 30 observation window (105 digests),
developed in the claude.ai analysis session of 2026-07-30.

**1. Survivorship bias in the median (pattern signal, high confidence).**
Median asking rose $68,605 → $71,079 over the window while every
criteria-matching car cleared out: Cary ($65,980), Fort Pierce ($67,998),
Sycamore (~$66,291), Critz (~$66,958). The rising median reflects adverse
selection of survivors — expensive stale inventory (Hampton $80,345/91 DoL,
RBM Atlanta $71,973, Kingsport $74,531) — not rising transaction prices.
Practical implication: ignore the pool median as a market benchmark. The
real benchmark is the clearing band where qualifying cars actually
transact: $65,980–$67,998, stable across three months.

**2. Stale-inventory decay clustering (pattern signal, moderate confidence).**
Cars that sit show price cuts clustered at roughly day 25–35, day 55–65,
and day 85+, with each cut larger than the last. Observed decay: RBM
Atlanta −4.5% over 91 days (4 cuts, accelerating), Kingsport −9.7%
($82,564 → $74,531), Durham −5.9%, Tiverton pair −2.3% by day 74.
Counter-archetype: Hampton, 91 days, zero drops — some dealers never
capitulate; don't waste calls on them. Practical implication for November:
a car first listed in September and still active in late November will be
2–3 cuts deep. That's the entry point.

**3. Month-end drop clustering now 4-for-4 (pattern signal, low-moderate
confidence — needs SQLite validation).**
Every month-end window in the dataset produced above-baseline drop
activity: Apr 29 (5 real drops, $6,200 aggregate, vs 0–1/day baseline),
May 24–26 (Sycamore −$1,700 aggregate), Jun 29 (Lynnfield −$1,500),
Jul 30 (North Orlando −$1,000). Directionally consistent with monthly
close reporting to MBUSA, but digest movers only capture above-threshold
drops and n=4. Validate against price_history table before treating as
load-bearing for November timing.

**November 2026 projection (from the 2026-07-30 model session):**
qualifying watchlist matches projected to list at $63,500–$66,500;
negotiated closes $62,000–$65,000 achievable by stacking stale-inventory
targeting + Nov 27–30 timing + MBUSA-portal arbitrage + warranty closer.
Key model risk: if the pool is still ~17 in October (supply stays thin),
sellers keep pricing power and the band shifts up $1,500–2,000.

**Validation (2026-07-30, [analysis/eom_pattern.md](analysis/eom_pattern.md)):**
month-end partially held — a real but modest day-28–30 frequency bump
(+58% drops/day, no magnitude effect, mid-month days 13/17/18 spike
equally); decay clustering did not hold — cuts front-load in the first
~3 weeks with flat ~1.5% sizes, no 25–35/55–65/85+ clusters, so finding 2
drops to low confidence and finding 3 stays low-moderate.
