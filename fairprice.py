"""Percentile-rank scoring for currently-active listings.

Per PROJECT.md "Fair-price scoring": each currently-active VIN gets ranked
against comparable listings. The result is cached on `listings.fair_price_pct`
(0–99, lower = cheaper) and `listings.fair_price_tier` ('strict' / 'loose' /
'broad' / NULL).

**Tiered comp strategy** (per the April 2026 reality check in PROJECT.md):
strict matching (year ±1, mileage ±15k) produces <5 comps for most listings
in this thin national market, so we fall back to looser tiers and tag the
result so notifications can convey confidence.

  strict: same trim, year ±1, mileage_first_seen ±15k
  loose:  same trim, year ±2, mileage_first_seen ±25k
  broad:  same trim, year ±3, mileage_first_seen ±40k

The first tier with ≥5 comps wins. Below that floor in every tier, return
(None, None) and the notification says "insufficient comps".

**Percentile rank** uses the standard midrank ("average") tie-handling so a
listing tied with N others gets a stable percentile in the middle of the
tied range, not pinned to either end. Formula:

  midrank = (count_lt + count_le) / 2
  pct = round(100 * midrank / total_in_pool)

The target listing is included in its own pool — we're ranking it within a
population that includes itself, which is the conventional definition.

Run nightly via `.github/workflows/fairprice.yml`. The watcher also reads
this module at notification time to compute fresh percentiles for new
listings (which haven't been recomputed yet by the nightly job).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from db import connect, migrate

# (tier_name, year_window, mileage_window). Order matters: strict first.
TIERS: tuple[tuple[str, int, int], ...] = (
    ("strict", 1, 15_000),
    ("loose",  2, 25_000),
    ("broad",  3, 40_000),
)
MIN_COMPS = 5  # below this, the pool is too thin to be meaningful


def _percentile_midrank(target_price: int, all_prices: list[int]) -> int:
    """Midrank percentile (0-99). Lower = cheaper. Target must be in `all_prices`."""
    less_than = sum(1 for p in all_prices if p < target_price)
    less_or_equal = sum(1 for p in all_prices if p <= target_price)
    midrank = (less_than + less_or_equal) / 2
    pct = round(100 * midrank / len(all_prices))
    # Clamp to schema's CHECK range (0..99).
    return max(0, min(99, pct))


def _fetch_target(conn: sqlite3.Connection, vin: str) -> sqlite3.Row | None:
    """Returns row with (vin, year, trim, mileage_first_seen, current_price)
    for the target VIN, or None if the VIN isn't tracked or has no price.

    The price>0 filter skips API anomaly rows — see digest._list_drops
    for context."""
    return conn.execute(
        "SELECT l.vin, l.year, l.trim, l.mileage_first_seen, "
        "       (SELECT price FROM price_history WHERE vin = l.vin AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS current_price "
        "FROM listings l WHERE l.vin = ?",
        (vin,),
    ).fetchone()


def _fetch_comp_prices(
    conn: sqlite3.Connection,
    target_vin: str, target_trim: str, target_year: int, target_mileage: int,
    year_window: int, mileage_window: int,
) -> list[int]:
    """Return current prices for active+reappeared listings matching the comp window.

    Includes the target itself (it's part of its own population for ranking).
    Excludes 'gone' listings (stale data), NULL prices, and zero/negative
    prices (API anomaly rows).
    """
    rows = conn.execute(
        "SELECT (SELECT price FROM price_history WHERE vin = l.vin AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS current_price "
        "FROM listings l "
        "WHERE l.status IN ('active', 'reappeared') "
        "  AND l.trim = ? "
        "  AND l.year IS NOT NULL "
        "  AND ABS(l.year - ?) <= ? "
        "  AND l.mileage_first_seen IS NOT NULL "
        "  AND ABS(l.mileage_first_seen - ?) <= ?",
        (target_trim, target_year, year_window,
         target_mileage, mileage_window),
    ).fetchall()
    return [r["current_price"] for r in rows if r["current_price"] is not None]


def compute_percentile(
    conn: sqlite3.Connection, vin: str,
) -> tuple[int | None, str | None]:
    """Compute (fair_price_pct, fair_price_tier) for a single VIN.

    Returns (None, None) if the target lacks data or no tier yields ≥5 comps.
    """
    target = _fetch_target(conn, vin)
    if target is None or target["current_price"] is None:
        return None, None
    if target["year"] is None or target["mileage_first_seen"] is None:
        return None, None

    for tier_name, year_window, mileage_window in TIERS:
        prices = _fetch_comp_prices(
            conn,
            target_vin=vin,
            target_trim=target["trim"],
            target_year=target["year"],
            target_mileage=target["mileage_first_seen"],
            year_window=year_window,
            mileage_window=mileage_window,
        )
        if len(prices) >= MIN_COMPS:
            return _percentile_midrank(target["current_price"], prices), tier_name

    return None, None  # pool too thin in every tier


def recompute_all(conn: sqlite3.Connection) -> dict:
    """Recompute fair_price_pct and fair_price_tier for every active+reappeared VIN.

    Returns a stats dict for logging. Caller should commit if connection
    is theirs.
    """
    rows = conn.execute(
        "SELECT vin FROM listings WHERE status IN ('active', 'reappeared')"
    ).fetchall()

    counts = {"strict": 0, "loose": 0, "broad": 0, "insufficient": 0}
    for row in rows:
        pct, tier = compute_percentile(conn, row["vin"])
        conn.execute(
            "UPDATE listings SET fair_price_pct = ?, fair_price_tier = ? WHERE vin = ?",
            (pct, tier, row["vin"]),
        )
        counts[tier or "insufficient"] += 1

    return {"total": len(rows), **counts}


def format_percentile(pct: int | None, tier: str | None) -> str:
    """Format the percentile string for inclusion in notification bodies.

    Lower percentile = cheaper relative to comps, so we say so explicitly:
    "23rd percentile (loose comps) — cheaper than 77% of comparable cars".
    """
    if pct is None:
        return "fair price: insufficient comps"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(pct % 10, "th") if not (10 <= pct % 100 <= 13) else "th"
    cheaper_than = 100 - pct
    return f"fair price: {pct}{suffix} percentile ({tier} comps) — cheaper than {cheaper_than}% of comparable cars"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute fair-price percentiles for active listings.")
    parser.add_argument("--vin", help="Compute and print for one VIN; do not write to DB")
    args = parser.parse_args(argv)

    conn = connect()
    try:
        migrate(conn)
        if args.vin:
            pct, tier = compute_percentile(conn, args.vin)
            print(f"{args.vin}: pct={pct} tier={tier}")
            print(format_percentile(pct, tier))
        else:
            stats = recompute_all(conn)
            conn.commit()
            print(
                f"fairprice: recomputed {stats['total']} listings — "
                f"strict={stats['strict']} loose={stats['loose']} "
                f"broad={stats['broad']} insufficient={stats['insufficient']}"
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
