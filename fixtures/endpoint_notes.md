# MBUSA CPO Inventory API — Endpoint Notes

Status: **CONFIRMED WORKING** as of 2026-04-25.
Recon completed via Chrome DevTools + URL probing.
This file is the authoritative reference for the watcher's parser.

---

## The endpoint

**URL:** `https://nafta-service.mbusa.com/api/inv/v1/en_us/used/vehicles/search`

**Method:** GET

**Auth:** none. Public endpoint, no API key, no bearer token, no session cookie required.

**CORS check:** The API may verify the `Origin` or `Referer` header
matches `https://www.mbusa.com`. If the watcher gets 403 responses
in production, add these headers and retry. (Current behavior: works
fine without them when called from a server-side script.)

---

## Canonical query (the watcher's target)

```
https://nafta-service.mbusa.com/api/inv/v1/en_us/used/vehicles/search?count=12&distance=ANY&invType=cpo&class=E&model=E450S4&bodyStyleId=WGN&resvOnly=false&sortBy=distance-asc&start=1&withFilters=true&zip=90210
```

This URL returns CPO E450 4MATIC All-Terrain wagons nationwide,
sorted by distance from Beverly Hills (90210), 12 per page.

## Query parameters

| Param | Required? | Example | Notes |
|---|---|---|---|
| `class` | yes | `E` | Model class. `E` = E-Class. |
| `invType` | yes | `cpo` | `cpo` = Certified Pre-Owned. |
| `zip` | yes | `90210` | Buyer ZIP for distance calculation. |
| `distance` | yes | `ANY` | Radius. `ANY` = nationwide. Numeric (`50`, `100`, `500`, `1000`) also accepted. |
| `count` | yes | `12` | **Page size.** Values above the remaining-record count return fewer records or none (see "Pagination"). Keep at `12`. |
| `start` | yes | `0` | **Zero-based page index** (not an offset). Page `p` returns records `[p*count, (p+1)*count)`. Page 0 is the nearest cars. |
| `sortBy` | yes | `distance-asc` | Sort order. `distance-asc` is the safe default. |
| `resvOnly` | yes | `false` | When `true`, returns only reservation-required vehicles. We want `false`. |
| `withFilters` | yes | `true` | **Required.** `false` returns 400. Response always includes facets. |
| `model` | optional | `E450S4` | Drivetrain code. Without this, results include all E-Class. |
| `bodyStyleId` | optional | `WGN` | Body style filter. `WGN` = wagon. Without this, includes sedans/coupes/etc. |

---

## Pagination — `start` is a page index

**Corrected 2026-08-19. This supersedes the "the API doesn't actually
paginate" note that stood here from 2026-04-26 to 2026-08-19.**

The contract is ordinary page-based pagination:

- **`start` = zero-based page index. `count` = page size.** Page `p`
  returns records `[p*count, (p+1)*count)`.
- A page with fewer than `count` records is the **last** page. Past the
  end you get 0 records.
- Verified live 2026-08-19 against a 23-record pool:
  `start=0&count=12` → 12 records (the 12 nearest cars);
  `start=1&count=12` → 11 records (short page → end);
  `start=2&count=12` → 0 records.
  `count=6` walks it in 4 pages: 6 + 6 + 6 + 5.
- `result.pagedVehicles.paging.totalCount` reported 23 and the walk
  collected exactly 23, so totalCount is at least sometimes right. The
  watcher still overwrites it with the count it actually collected, and
  logs a `coverage_shortfall` anomaly when the walk comes up short.

### Why the old notes read it backwards

The April probing was accurate but interpreted with the semantics
inverted. `start=1, count=12` and `start=2, count=12` really do return
disjoint 12-record sets — because they are *pages 1 and 2*. `start=1,
count=24` really is a superset of `start=2, count=12` — because page 1 at
size 24 spans records 24–47, which contains records 24–35. Everything
observed is consistent with page indexing; nothing required a "the API
doesn't paginate" theory.

Cost of the misreading: the watcher pinned `start=1` and varied `count`,
so it only ever read records 12 and beyond. **Page 0 — the nearest
listings — was never fetched for the life of the project.** On 2026-08-19
page 0 held two CA cars 71.8 miles from the target ZIP, the closest in the
feed, neither of which had ever entered the DB. The strategy also failed
outright once the pool fell to 23: at that size `count=24` returns 0
records, so the union collapsed to 11 and tripped `EXPECTED_MIN_POOL`,
aborting every poll for ~16 hours on 2026-08-18/19.

### Proof that the API did not change (and why nobody noticed for 4 months)

Worth recording, because `sample_response.json` shows a Los Angeles car as
record #1 and that looks like evidence the API used to behave differently.
It isn't. The fixture and the first automated snapshot are adjacent pages of
the same distance-sorted list, captured the same day:

| | records | distance range | n |
|---|---|---|---|
| `fixtures/sample_response.json` | 0–11 (page 0) | 9.7 → 1,373 mi | 12 |
| `raw_snapshots/20260426_155037.json.gz` | 12–47 (pages 1@12 ∪ 1@24) | 1,552 → 2,532 mi | 36 |

**Zero VIN overlap. The fixture's farthest car (1,373 mi) is nearer than the
snapshot's nearest (1,552 mi). 12 + 36 = 48 = the true pool that day.** So
`start=1` already meant "second page" on 2026-04-26, the same day the recon
notes declared it canonical. The semantics never changed — the recon
captured page 0 by hand, then wrote down `start=1`, and the automation used
`start=1` from its very first run.

**Why it stayed invisible:** the fixture *is* page-0 data, so `DRY_RUN=1`
replay and the entire test suite validated against a payload full of LA
cars. Local runs looked correct; only the live path was wrong. A fixture
captured differently from how production queries is a blind spot — when
changing the query contract, re-verify against the live endpoint, not the
fixture. (`test_fetch_all_walks_pages_until_short_page` now pins the walk to
page 0 so this specific regression can't return silently.)

### Current strategy: walk the pages

`scrape.fetch_all()` requests page 0, 1, 2, … at `PAGE_SIZE = 12` until a
short page arrives, unions by VIN (the page boundary has been observed
repeating one record), and rewrites `paging` with the real collected
count. `MAX_PAGES = 25` guards against a contract change that yields full
pages forever.

At 30-min polling, that's 4 requests/hour total — still well within
polite limits.

---

## Required headers (minimal working set)

```
Accept: application/json
User-Agent: mb-wagon-watcher/1.0 (personal research; pwysocan@gmail.com)
```

May be required if 403 responses occur:

```
Origin: https://www.mbusa.com
Referer: https://www.mbusa.com/en/cpo/inventory/search
```

**Do NOT** copy the User-Agent from DevTools captures — when device
emulation is on, DevTools sends a forged Android UA. Use an honest UA
identifying the watcher.

---

## Response shape

```
{
  "result": {
    "pagedVehicles": {
      "records": [ /* array of vehicle objects */ ],
      "paging": {
        "totalCount": 53,
        "currentOffset": 0,
        "currentCount": 12
      }
    },
    "facets": { /* aggregations - useful for sanity checks */ }
  },
  "status": { "code": 200, "ok": true, "tmstmp": "...", "traceId": "..." },
  "messages": [],
  "success": true
}
```

`success: false` or `status.code != 200` indicates an error. The
watcher should abort and not write to the DB on any non-200.

---

## Per-vehicle field mapping

**Critical structural rule (verified against `sample_response.json`,
2026-04-25):** "live" per-vehicle data — mileage, photos, options, full dealer
info — lives under `record.usedVehicleAttributes.*`, NOT at the record root.
Record #1 of any response often duplicates these to top-level keys, but
records 2+ do not. The original recon eyeballed record #1 and got the paths
wrong; corrected paths below.

| Watcher field | JSON path | Notes |
|---|---|---|
| `vin` | `record.vin` | unique key |
| `year` | `record.year` | string in JSON — cast to int |
| `model` | `record.modelName` | e.g. "E 450 4MATIC All-Terrain" |
| `trim` | `record.modelId` | "E450S4" |
| `body_style` | `record.bodyStyleId` | "WGN" |
| `mbusa_price` | `record.msrp` | top-level. **MISLEADING NAME** — this is dealer asking price, NOT original MSRP. Mirrored at `record.usedVehicleAttributes.dsrp`. |
| `mileage_first_seen` | `record.usedVehicleAttributes.mileage` | float, in miles |
| `exterior_color` | `record.paint.name` | display name |
| `exterior_color_code` | `record.exteriorMetaColor` | "BLK"/"WHT"/etc. |
| `interior_color` | `record.upholstery.name` | |
| `engine` | `record.engine` | |
| `is_certified` | `record.usedVehicleAttributes.certified` | boolean |
| `dealer_id` | `record.dealerId` | top-level. Also at `record.usedVehicleAttributes.dealer.id`. |
| `dealer_name` | `record.usedVehicleAttributes.dealer.name` | top-level `record.dealer.name` is unreliable |
| `dealer_zip` | `record.usedVehicleAttributes.dealer.address[0].zip` | |
| `dealer_state` | `record.usedVehicleAttributes.dealer.address[0].state` | |
| `dealer_distance_miles` | `record.usedVehicleAttributes.dealer.address[0].location.dist` | string in JSON, cast to float |
| `dealer_site_url` | `record.usedVehicleAttributes.dealer.url` | for cross-source price check |
| `photo_url` | `record.usedVehicleAttributes.images[0]` | first real photo. (`exteriorBaseImage` was mentioned in early notes as a stock-render fallback but is absent from every live record — ignore.) |
| `stock_id` | `record.stockId` | dealer-internal stock number. Also at `record.usedVehicleAttributes.stockId`. |
| `options_json` | `record.usedVehicleAttributes.optionList` | array of `{code, text}` — store as JSON blob |

---

## Discovered model & body codes

- `E` = E-Class (parameter: `class`)
- `E450S4` = E 450 4MATIC (parameter: `model`) — applies to both sedan and All-Terrain
- `WGN` = Wagon (parameter: `bodyStyleId`)
- Other facet values from `facets.modelDesignation`:
  - `E350W4` = E 350 4MATIC Sedan
  - `E450W4` = E 450 4MATIC Sedan
  - `E63S4S` = AMG E 63 S Wagon (excluded by criteria)
  - `E53ES4` = AMG E 53 HYBRID Wagon (excluded)

Color codes from `facets.color`:
- `BLK` Black, `WHT` White, `GRY` Grey, `SLV` Silver, `BLU` Blue, `RED` Red

---

## Politeness

- 30-minute polling interval (per PROJECT.md)
- Single-threaded; no concurrent requests
- Honor `Retry-After` if rate-limited
- Use the watcher's own User-Agent
- Cache the raw gzipped response to `raw_snapshots/` on every run

---

## Known fragility

The API returns non-200 status codes for:
- `withFilters=false` → 400 Bad Request

(`count > 12` does NOT return 500 — the original recon claim was wrong.
Large `count` values are page sizes: they return whatever remains on that
page, which is often fewer records than requested and sometimes none, with
no error code. `count=0` returns 500. `sortBy` values other than
`distance-asc`/`distance-desc` (e.g. `price-asc`, `mileage-asc`,
`year-desc`) return 400.)

The watcher should treat any 4xx/5xx response as an abort signal:
log the failure to the `runs` table, send a high-priority alert, and
exit nonzero. Do NOT corrupt the DB by writing partial data.
