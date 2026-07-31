# MARKET_NOTES

Running market observations for the wagon watch. Newest entries on top.
Convention per entry: dated section header, observation → interpretation
structure, pattern signals marked with confidence.

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
