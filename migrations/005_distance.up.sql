-- The MBUSA API already returns distance from the query ZIP (90210) to each
-- dealer in record.usedVehicleAttributes.dealer.address[0].location.dist.
-- Persist it on listings so the digest, dashboard, and watchlist queries
-- can sort/filter by distance without recomputing on every read. Recorded
-- on first sight only — a stable property of the dealer, not the listing.

ALTER TABLE listings ADD COLUMN distance_miles REAL;
