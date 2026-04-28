-- Per PROJECT.md "Fair-price scoring": cache the percentile-rank result on
-- the listings row so notifications and the digest can read it without
-- recomputing each time. fair_price_tier records which comp pool was used
-- (strict / loose / broad) so the notification can convey confidence.
-- Both nullable: fewer than 5 comps in any tier yields NULL/NULL, and the
-- notification surfaces "insufficient comps" rather than a bogus percentile.

ALTER TABLE listings ADD COLUMN fair_price_pct INTEGER
    CHECK (fair_price_pct IS NULL OR (fair_price_pct >= 0 AND fair_price_pct <= 99));

ALTER TABLE listings ADD COLUMN fair_price_tier TEXT
    CHECK (fair_price_tier IS NULL OR fair_price_tier IN ('strict', 'loose', 'broad'));
