# Handoff — Price History Data Exposure

For Claude Code, in the wagon-watcher repo. Read this before doing
anything else.

This is a small, additive change. No refactor, no UI work, no
dashboard changes. The goal is to expose the price history data
that already exists in `data/inventory.db` as a publicly-fetchable
JSON file, so it can be consumed by the dashboard v2 (separate
handoff, ships later) and by external readers.

---

## What this adds

A single new artifact: `data/price_history.json` — committed on
every reconcile run, alongside the existing `data/latest.json`.

Format (JSON):

```json
{
  "generated_at": "2026-04-29T14:30:00Z",
  "schema_version": 1,
  "vins": {
    "W1KLH6FB0SA147147": {
      "year": 2025,
      "trim": "E450S4",
      "dealer": "Mercedes-Benz of Cary",
      "first_seen_at": "2026-04-26T09:14:08Z",
      "current_price": 65980,
      "current_mileage": 5143,
      "status": "active",
      "observations": [
        {"observed_at": "2026-04-26T09:14:08Z", "price": 67680, "mileage": 5143},
        {"observed_at": "2026-04-29T11:58:03Z", "price": 65980, "mileage": 5143}
      ],
      "stats": {
        "all_time_low": 65980,
        "all_time_high": 67680,
        "total_drop_pct": -2.51,
        "n_observations": 2,
        "days_observed": 3
      }
    },
    "...": "..."
  }
}
```

Format rules:

- **Top-level keyed by VIN** for O(1) client-side lookups
- **`observations` array is per-distinct-price-or-status-change**,
  not per cron run. We don't need ~36 redundant observations per
  day for a stable price; we need the changes. Reconciler already
  has this logic — reuse the existing `price_history` table that
  step 6 (fairprice) populates.
- **`stats` block is computed server-side** (Python), not in the
  browser. Cheaper to compute once than for every chart render.
- **`status` is the current state** (active, gone, reappeared) —
  matches the listings table's `status` column.
- **`schema_version` is included** so the dashboard can detect
  format changes and degrade gracefully.

## Where to write it

Same logic as `latest.json`:

1. After every successful reconcile run
2. Write to `data/price_history.json`
3. Get committed to `main` by the existing workflow's `git add` step
4. Vercel redeploys; the file becomes available at:
   - `https://wagon-watcher.vercel.app/data/price_history.json`
   - `https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/data/price_history.json`

Both URLs work; both are public.

## File size considerations

Rough math:
- 36 active VINs at any given time
- ~30 historical VINs (gone but still in DB)
- ~5 observations per VIN average over 30 days
- ~250 bytes per observation in JSON

Total: ~80KB unminified, ~20KB after gzip. Trivial to fetch even
on mobile. No need to paginate or split.

After 6 months: ~500KB unminified, ~120KB gzipped. Still fine.

After 12 months: ~1MB. At that point, consider:
- Pruning observations older than 90 days for `gone` VINs
- Pruning entire VINs that went gone >30 days ago
- Splitting into per-month files

But that's a 6-12 months from now problem. Don't pre-optimize.

## Implementation

Minimal addition to `analytics.py` (or wherever `latest.json` is
generated — likely `run.py`). Add a function:

```python
def export_price_history(db_path: Path, output_path: Path) -> None:
    """Export VIN-keyed price history for the dashboard.

    Reads from listings, price_history, and reconciler events to
    construct a per-VIN observation series with computed stats.
    """
    import json
    import sqlite3
    from datetime import datetime, timezone

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all VINs (active + recently gone) with their current state
    listings = conn.execute("""
        SELECT vin, year, trim, dealer_name, first_seen_at,
               asking_price, mileage, status
        FROM listings
        WHERE status != 'gone' OR last_seen_at > datetime('now', '-30 days')
    """).fetchall()

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "vins": {},
    }

    for row in listings:
        vin = row["vin"]
        # Get observation series for this VIN
        observations = conn.execute("""
            SELECT observed_at, price, mileage
            FROM price_history
            WHERE vin = ?
            ORDER BY observed_at ASC
        """, (vin,)).fetchall()

        obs_list = [
            {"observed_at": o["observed_at"], "price": o["price"], "mileage": o["mileage"]}
            for o in observations
        ]

        # Compute stats
        prices = [o["price"] for o in observations]
        if not prices:
            continue

        first_price = prices[0]
        current_price = prices[-1]
        all_time_low = min(prices)
        all_time_high = max(prices)
        total_drop_pct = round((current_price - first_price) / first_price * 100, 2)

        # Days observed: from first_seen to now
        first_seen = datetime.fromisoformat(row["first_seen_at"].replace("Z", "+00:00"))
        days_observed = (datetime.now(timezone.utc) - first_seen).days

        result["vins"][vin] = {
            "year": row["year"],
            "trim": row["trim"],
            "dealer": row["dealer_name"],
            "first_seen_at": row["first_seen_at"],
            "current_price": current_price,
            "current_mileage": row["mileage"],
            "status": row["status"],
            "observations": obs_list,
            "stats": {
                "all_time_low": all_time_low,
                "all_time_high": all_time_high,
                "total_drop_pct": total_drop_pct,
                "n_observations": len(observations),
                "days_observed": days_observed,
            },
        }

    output_path.write_text(json.dumps(result, indent=2))
    conn.close()
```

Then call it from the reconcile pipeline right after
`export_latest()`:

```python
export_price_history(
    db_path=Path("data/inventory.db"),
    output_path=Path("data/price_history.json"),
)
```

## Tests

Three tests are sufficient:

1. **Empty DB produces empty `vins` dict** — graceful behavior on
   first run before any data exists
2. **Single VIN with three observations produces correct series** —
   fixture-driven test with synthetic price drops, verify stats
   are computed correctly (low, high, total_drop_pct)
3. **Gone VIN older than 30 days is excluded** — cutoff logic
   works; we don't accumulate stale data forever

Use existing test fixtures and the same pattern as the
`test_latest_json_export` tests if they exist; otherwise mirror
the `test_reconcile.py` style.

## What's explicitly NOT in this handoff

- No dashboard changes. The dashboard v1 stays exactly as it is.
- No UI work. Dashboard v2 (which will consume this file) is a
  separate handoff that ships later.
- No alerts or notification changes.
- No schema migrations — the `price_history` table already exists
  from step 6.
- No pruning logic. Just emit everything for now; we'll add a
  retention policy if file size becomes a problem in 6+ months.
- No CDN/caching headers. Default Vercel behavior is fine.

## Commit hygiene

Single commit:

```
analytics: export per-VIN price history to data/price_history.json

Mirrors the latest.json export with a richer per-VIN observation
series. Used by the upcoming dashboard v2 (stock-ticker layout)
and available as a public artifact for external readers.

Format documented in the function docstring. Schema version is 1;
bump if the format changes in a breaking way.
```

That's it. ~30 minutes of work including tests. Ship and move on.

---

## Verification after deploy

After the first cron run that includes this change, verify:

1. The file exists in the repo at `data/price_history.json`
2. Vercel has redeployed and served the file at its public URL
3. The file is valid JSON (paste into a JSON validator)
4. Spot-check one VIN's observations against the alerts log —
   the prices should match what the alert log shows

If all four pass, the data exposure is working and the dashboard
v2 work can begin.
