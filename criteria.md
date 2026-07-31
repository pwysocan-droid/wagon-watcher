# criteria.md — canonical buying spec

This file is the canonical specification that the watchlist DB rule
implements — the active `watchlist` row labeled "Within criteria.md"
(`{"min_year":2024,"max_mileage":15000,"max_price_all_in":68000,
"trim":"E450S4","body_style":"WGN"}`) encodes the machine-checkable
subset below. Analyses (analysis/survival_v1.md, analysis/eom_pattern.md,
MARKET_NOTES.md) should cite this file when they reference "criteria" or
the qualifying/watchlist subset.

## Hard criteria (watchlist-enforced)

- **Model years:** 2024–2026 (2025+ preferred)
- **Trim:** E450 4MATIC All-Terrain only (`E450S4`, wagon) — no AMG E63
- **Max mileage:** 15,000 (hard ceiling)
- **Max price all-in to LA:** $68,000

## Hard criteria (manual verification, not machine-checkable)

- Factory Mercedes CPO required
- Clean Carfax AND AutoCheck, no accidents

## Benchmark config

The config a candidate is scored against; misses are negotiation points,
not automatic disqualifiers:

- Leather Package P34
- Winter Package
- Panoramic moonroof
- Burmester 4D
- 19" or 20" wheels
- Heated memory front seats
- Wood trim
- Full driver-assist suite

## Change control

If the spec changes, update this file AND the watchlist row's `spec_json`
in `data/inventory.db` together — the DB row is the enforcement, this file
is the record. Note the change in MARKET_NOTES.md if it shifts what
"qualifying" means for ongoing analyses.
