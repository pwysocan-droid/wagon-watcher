-- Per PROJECT.md "Cross-source price discrepancy detection". The watcher
-- captures the dealer's own website price for cross-checking against the
-- MBUSA-portal price (record.msrp from the API). When the dealer site asks
-- meaningfully more than MBUSA, that's a Tier 1 negotiation-leverage signal.
--
-- All three columns are nullable: the MBUSA API doesn't give us a per-VIN
-- URL, only the dealer's homepage, so the extractor is best-effort. A NULL
-- dealer_site_price means "not found / extractor missed / fetch failed",
-- not "$0".

ALTER TABLE listings ADD COLUMN dealer_site_price INTEGER;
ALTER TABLE listings ADD COLUMN dealer_site_url TEXT;
ALTER TABLE listings ADD COLUMN dealer_site_checked_at TIMESTAMP;
