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
| `count` | yes | `12` | Records to return. NOT capped at 12 — `count=24` works. `count=30+` returns truncated/anomalous results (see "Pagination" below). |
| `start` | yes | `1` | Misnomer — does NOT behave as an offset. Different `start` values return *disjoint* 12-record windows; values ≥12 return 0 records. Use `start=1` always; vary `count` instead. |
| `sortBy` | yes | `distance-asc` | Sort order. `distance-asc` is the safe default. |
| `resvOnly` | yes | `false` | When `true`, returns only reservation-required vehicles. We want `false`. |
| `withFilters` | yes | `true` | **Required.** `false` returns 400. Response always includes facets. |
| `model` | optional | `E450S4` | Drivetrain code. Without this, results include all E-Class. |
| `bodyStyleId` | optional | `WGN` | Body style filter. `WGN` = wagon. Without this, includes sedans/coupes/etc. |

---

## Pagination — the API doesn't actually paginate

**Important — this contradicts the original recon notes.** Re-verified
2026-04-26 by direct probing: the API does NOT support offset-style
pagination via `start`. Original recon assumed `start=13`, `start=25`
would give pages 2 and 3; in reality both return zero records.

What the API actually does:

- `start=1, count=12` → some 12 VINs (set A).
- `start=2, count=12` → a *different* 12 VINs (set B). **Zero overlap with A.**
- `start>=12, count=12` → **0 records.**
- `start=1, count=24` → 24 VINs (set C). **C ⊃ B; C ∩ A = ∅.**
- `start=1, count=30+` → fewer records than asked (returns are truncated
  in a non-obvious way; assume broken).

The `result.pagedVehicles.paging.totalCount` field is also unreliable —
it reports 53 even when the modelDesignation facet says only 34 E450S4
listings exist.

### The workaround: union strategy

To cover the full filtered pool (~36 unique VINs for E450S4+WGN), the
watcher makes **two calls per poll**, both with `start=1`:

1. `count=12, start=1` → set A (12 VINs)
2. `count=24, start=1` → set C (24 VINs, disjoint from A)

Union by VIN, dedupe → ~36 VINs. Verified deterministic across 3
consecutive polls (same VINs, same prices).

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

(`count > 12` does NOT actually return 500 — the original recon claim was
wrong. `count=24` returns 24 records cleanly. `count=30+` quietly returns
fewer records than requested with no error code.)

The watcher should treat any 4xx/5xx response as an abort signal:
log the failure to the `runs` table, send a high-priority alert, and
exit nonzero. Do NOT corrupt the DB by writing partial data.
