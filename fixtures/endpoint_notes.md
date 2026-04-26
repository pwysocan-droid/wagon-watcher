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
| `count` | yes | `12` | Page size. **HARD CAP AT 12.** Higher values return 500. |
| `start` | yes | `1` | Pagination cursor (1-indexed). Next page = `start + count`. `start=0` also works for first page. |
| `sortBy` | yes | `distance-asc` | Sort order. `distance-asc` is the safe default. |
| `resvOnly` | yes | `false` | When `true`, returns only reservation-required vehicles. We want `false`. |
| `withFilters` | yes | `true` | **Required.** `false` returns 400. Response always includes facets. |
| `model` | optional | `E450S4` | Drivetrain code. Without this, results include all E-Class. |
| `bodyStyleId` | optional | `WGN` | Body style filter. `WGN` = wagon. Without this, includes sedans/coupes/etc. |

---

## Pagination

Offset-based, 1-indexed. Walk the full pool with sequential calls:

- Call 1: `start=1&count=12` → records 1–12
- Call 2: `start=13&count=12` → records 13–24
- Call 3: `start=25&count=12` → records 25–34
- Continue until `result.pagedVehicles.paging.totalCount` is reached

For E450S4+WGN, the national pool was 34 cars on 2026-04-25, requiring
3 paginated calls per poll. At 30-min polling = 6 requests/hour total.

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
- `count > 12` → 500 Server Error
- `withFilters=false` → 400 Bad Request
- `sortBy=price-asc` (untested; may also fail — use `distance-asc`)

The watcher should treat any 4xx/5xx response as an abort signal:
log the failure to the `runs` table, send a high-priority alert, and
exit nonzero. Do NOT corrupt the DB by writing partial data.
