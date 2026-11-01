# Learnings: what six months of watching one car market taught

**Outcome:** the search ended in a purchase. The car is a 2024 Mercedes E450
All-Terrain, black over black leather, 4,786 miles, CPO, from Mercedes-Benz of
Manhattan. The watcher was paused on 2026-11-01. The final price and financing
aren't recorded here because this repo is public.

**Scale:** the watcher made 2,697 successful scrapes between 2026-04-26 and
2026-10-30. It tracked 220 cars and recorded 808 price changes. See
[MARKET_NOTES.md](MARKET_NOTES.md), [analysis/](analysis/) and
[decision-log.md](decision-log.md) for the detail.

## The short version

1. **The watcher's real value was finding the market's pattern, not catching a
   deal.** It told us what a fair price was, how fast cars move, and which
   dealers cut. The car itself was found by watching and then negotiating.
2. **The written spec wasn't the real spec.** The only car that truly met it
   late in the search (Rochester, $65,095) was rejected on color. Color was
   the deciding constraint, and it was never in `criteria.md`.
3. **A national feed shows far less than the market.** It sees one sales
   channel, and asking prices only. The most useful facts came from outside
   it: dealer sites, Cars.com histories, and CarGurus.

## The market

How far to trust each point: **high** means it held on clean data after the
August scraper fix; **medium** means it's directional, from a small sample.

- **Ignore the median asking price (high).** It rises as good cars sell and
  overpriced ones sit, and it falls when older cars arrive. It never measured
  the market.
- **Qualifying cars sold in a narrow band (high):** about $66–68k from spring
  through September. That band was more useful than any average.
- **Qualifying supply was about one car a month (medium).** The July forecast
  of 3–5 cars in the buying window was about four times too high. Even with
  supply this thin, one did arrive (Rochester, Oct 21).
- **Fall was slower than summer (medium).** The median time to disappear went
  from 15 days to 21, and to 29 days for 2024+ cars.
- **Price at listing predicts a car's path (high).** Cheap cars go; cars listed
  above the 55th percentile tend to sit and become negotiable.
- **Cuts come early and are small (medium):** about 1.5–2%, with the first
  around day 9.
- **Month-end isn't a strategy (medium).** There are a few more cuts on days
  28–30, but they're no bigger, and at Ray Catena deep cuts fell mid-month.

## Dealers

Each dealer behaves consistently, so **a dealer's other cars predict how it
will treat yours**, even a model it has never listed before. This was the most
useful single technique in the project.

| Dealer type | Example | How it moves | What to do |
|---|---|---|---|
| Lot-wide sweeps, round steps | Manhattan (factory store), MB LA (Lithia), Rochester | Cuts on shared dates, $1–2k | Time the offer around the sweep |
| Market-tracking software | West Chester | Prices can go **up** | Don't assume waiting helps |
| Rare, large, unpredictable | Scarborough (Group 1) | Long flat stretches | Negotiate, don't wait |
| Price-to-market, little discount | Edison (Ray Catena) | Small nudges | Use comps, not haggling |
| Never moves | Hampton | No cuts in 171+ days | Skip |

Other dealer lessons:

- **Advertised prices aren't comparable.** Fees ranged from $0 to about $900,
  and some dealers fold them into the price. Compare out-the-door quotes only.
- **Responsiveness is a real factor.** The deal went to the dealer that
  answered. An unanswered email took Edison, the best spec, out of the running.
- **"Certified" needs checking.** One dealer's notes described a one-month
  warranty on a car MBUSA listed as CPO. Others said "certified" on cars that
  MBUSA didn't list.
- **Prices in listing notes can be wrong.** Manhattan's Cars.com listing said no
  added dealer fees, but they quoted $320.
- **"Gone" doesn't mean sold.** Some 90% of 2,000 gone events reversed. One
  "sold" car turned up two months later at another dealer, $4,600 cheaper.

## Buying

- **Set the walk-away number before talking to a dealer,** and record whether it
  includes fees, shipping and tax. Several of our numbers left that unclear.
- **Run several candidates at once.** A real alternative is what made it
  possible to pause Edison without losing momentum.
- **Log every call the same day,** with names and numbers.
- **Sell the old car separately.** Instant offers for the BMW came in about
  $4–5k under the auction estimate.
- **Check the delivered cost:** shipping, doc fees, and California use tax of
  about 10%, which added roughly $7k and was outside every headline number.
- **Quoted rates aren't advertised rates.** "From" rates ran a full point below
  the real 60-month rate. A 6.2% quote that looked high was close to the 6.66%
  national average.
- **Check for manufacturer CPO financing first.** It was the lowest rate found
  (3.99% for 36 months), and it was time-limited.

## The system

- **Silent failure was the main risk.** Every serious problem looked healthy:
  - A pagination bug hid the nearest cars for four months. It took the page 0
    fix on Aug 19 to expose it, and it biased every earlier analysis.
  - GitHub dropped most scheduled runs from Aug 27 with no error at all.
- **Monitor for absence, not just errors.** Stall and cadence alerts caught
  what success and failure signals couldn't.
- **GitHub's `schedule` trigger is best-effort.** Moving the cron off-peak
  didn't help: it stayed at 4–8 runs a day. The Mac trigger delivered 88% of
  runs afterward, but stopped when the laptop slept (longest gap: 6.2 hours).
- **Abort guards work.** When the feed dropped to 12 cars on Oct 30, the guard
  blocked those runs, so 17 cars weren't falsely marked gone.
- **Old thresholds create false alarms.** "Possible API cap" was a stale limit,
  not a cap; a live probe settled it.
- **Clean the data at the edges.** Fee flip-flopping and short feed dropouts
  needed explicit handling before any price or sale count could be trusted.

## What we got wrong

- **Forecasting MB LA's first cut from nearby dealers.** The guess was Oct
  19–26, but no real cut had come by Oct 30. Using the dealer's own other cars
  gave the better answer.
- **The November supply forecast,** built on truncated data.
- **Early claims from thin sources:** credit union rates and eligibility were
  stated too confidently, and had to be corrected.
- **Publishing live negotiation details in a public repo.** Offer and walk-away
  numbers were visible while the deal was open. Keep those private next time.

## If this is ever resumed

The API has reported `totalCount: 12` since Oct 30, down from 29, using the
same query. The cause is unknown: find it before re-enabling anything.

```sh
for w in watch heartbeat digest_daily digest fairprice; do gh workflow enable $w.yml; done
```

Then reinstall the launchd trigger using the steps in
`scripts/launchd/dispatch_watch.sh`, or use an always-on scheduler instead.
