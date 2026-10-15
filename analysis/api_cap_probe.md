# API-cap probe — are in-scope cars hidden from the feed?

**Date:** 2026-10-15
**Script:** [api_cap_probe.py](api_cap_probe.py) (live MBUSA API, about 30
requests)

**Why this probe.** Five cars look in scope but have never shown up in our
pool:
- A 2025 E450 All-Terrain at MB West Covina ($73,763, 5,830 mi, about
  25 mi from 90210) is listed on iSeeCars.
- On Cars.com, three cars outside the feed call themselves Mercedes
  certified:
  - **Youngstown OH** 2025, W1KLH6FB5SA129436, $60,778. The seller notes
    use certified-program language.
  - **Georgetown TX** 2025, W1KLH6FB8SA133447, $62,999. The notes say
    "Mercedes-Benz Certified".
  - **Valley Imports ND** 2025, W1KLH6FB2SA084620, $66,590. Cars.com labels
    it "Manufacturer Certified Pre-Owned".
- **Rochester MN** has a 2025 at $66,295.

The 2026-10-15 digest also flagged five runs under 30 listings as a
"possible API cap".

## Verdict: no cap. These cars aren't in MBUSA's CPO inventory.

| probe | result |
|---|---|
| Production query, nationwide, all pages | union **33 = totalCount 33**; no missing pages; none of the five targets present |
| 100-mi radius around each target dealer, production filters | West Covina 3, Youngstown 2, Georgetown 0, Fargo 0, Rochester 0 results. All far below one 12-record page, so a cap can't explain the absence. **Targets absent.** |
| Same, model filter dropped (class E + wagon) | 67 / 15 / 13 / 0 / 6 results. Mostly sedans, which shows `bodyStyleId` alone doesn't filter. **Targets absent.** MB Georgetown *is* in the CPO system with three E-Class sedans, but not this wagon. |
| Same, body-style filter dropped | Same as production. No mis-tagged body style. |
| `invType=used` | HTTP 500 for every ZIP. Plain-used inventory can't be checked through this endpoint. |

**Reading.** Looking within 100 miles, a search returns a handful of
records, nowhere near a cap, and the target cars still aren't there. Each
of these dealers either isn't listing the car as certified in MBUSA's
system, or isn't in the CPO program at all.

### What that means for each car

- **West Covina, Rochester:** non-CPO used cars. This is a gap in what the
  feed covers, not a fault in it. If a dealer will certify, the car can
  still be bought as CPO.
- **Youngstown, Georgetown:** "certified" appears in the dealer notes, but
  MBUSA doesn't list the car as CPO. The notes could be boilerplate, or
  certification could be pending. **Ask the dealer whether the car is
  certified in MBUSA's system, or will be before sale.** Treat the notes
  as a claim to check, not a fact.
- **Valley Imports:** this one was in the feed from Aug 26 until Sep 24,
  when it was recorded as sold at $66,590. Cars.com still lists it as
  manufacturer certified at the same price.
  - Mileage doesn't match: our feed recorded 6,505, the Cars.com listing
    says 12,618, and Cars.com's seller notes say 6,505.
  - Possible explanations:
    1. It sold, and the Cars.com listing is stale.
    2. It dropped out of the MBUSA locator while still for sale (pending
       deal, de-listed, or certification lapsed).
    3. It was driven (demo or loaner use) and taken off the CPO listing.
  - **Worth one call.** It's in the band at the asking price.

### The "possible API cap" anomaly is a stale threshold

`digest_daily.POOL_FLOOR = 30` was set when the pool was about 36. The real
nationwide pool is 33 today (union = totalCount), and was 22–30 through
September. A pool in the 28s is real thinness, not a cap.
**Proposed (not implemented):** remove the absolute floor and rely on the
coverage tripwire in `scrape.fetch_all`, which already logs
`coverage_shortfall` when the union falls short of totalCount.
Alternatively, lower the floor to about 18.

### No fix needed to pagination or radius

The production query already returns the whole national pool. The real
gap is **non-CPO inventory at Mercedes dealers**, and the MBUSA CPO
endpoint can't see it by design. That's covered by the weekly manual
sweep in MARKET_NOTES.md ("Endgame manual layer").
