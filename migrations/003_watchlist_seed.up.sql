-- Seed the standing buying criteria. Per HANDOFF_step5.md, this represents
-- what would have triggered an alert for VIN W1KLH6FB6SA153938 (the Keyes
-- wagon, $65,895 / 13,418 mi / 2025) had the watcher been live then.
-- Re-running the up is safe: ON CONFLICT DO NOTHING covers the dup case.
-- Watchlist match logic in reconcile.py will read spec_json and evaluate
-- AND-within-row, OR-across-rows.

INSERT INTO watchlist (kind, spec_json, label, created_at, active)
SELECT 'spec',
       '{"min_year":2024,"max_mileage":15000,"max_price_all_in":68000,"trim":"E450S4","body_style":"WGN"}',
       'Within criteria.md',
       CURRENT_TIMESTAMP,
       1
WHERE NOT EXISTS (SELECT 1 FROM watchlist WHERE label = 'Within criteria.md');
