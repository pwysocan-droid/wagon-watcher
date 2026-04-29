-- Stabilization filter state. The MBUSA API has been observed flapping
-- prices between two values across consecutive polls (e.g. on 2026-04-28
-- and 29 Sycamore/Critz/Asheville/Tysons Corner all alternated their
-- msrp on the same poll-cycle frequency). Without filtering, every flip
-- writes a price_history row and fires a Tier 3 silent alert.
--
-- Rule: a price change is "confirmed" — and inserted into price_history —
-- only after the new value has been observed for TWO consecutive polls.
-- The pending_* columns track the unconfirmed observation. If a VIN's
-- new price doesn't match either the last confirmed history row OR the
-- pending state, the new value replaces pending. If it matches pending,
-- it confirms (insert + clear pending). If it matches confirmed history,
-- the pending state is cleared (revert).

ALTER TABLE listings ADD COLUMN pending_price INTEGER;
ALTER TABLE listings ADD COLUMN pending_mileage INTEGER;
ALTER TABLE listings ADD COLUMN pending_observed_at TIMESTAMP;
