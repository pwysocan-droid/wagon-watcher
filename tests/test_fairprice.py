"""Tests for fairprice.py — tiered comp matching and midrank percentile."""
from datetime import datetime, timedelta, timezone

import pytest

import fairprice
from db import connect, migrate

T0 = datetime(2026, 4, 28, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    yield c
    c.close()


def _add_listing(conn, vin, year, mileage, price, trim="E450S4", status="active"):
    conn.execute(
        "INSERT INTO listings (vin, first_seen, last_seen, status, "
        " year, model, trim, body_style, mileage_first_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vin, T0, T0, status, year, "E 450 4MATIC All-Terrain", trim, "WGN", mileage),
    )
    conn.execute(
        "INSERT INTO price_history (vin, observed_at, price, mileage) "
        "VALUES (?, ?, ?, ?)",
        (vin, T0, price, mileage),
    )


# ---- _percentile_midrank --------------------------------------------------

def test_percentile_cheapest_unique():
    """Target is uniquely cheapest of 5 → very low percentile."""
    pct = fairprice._percentile_midrank(50_000, [50_000, 60_000, 70_000, 80_000, 90_000])
    assert pct == 10  # midrank = 0.5, 100*0.5/5 = 10


def test_percentile_most_expensive_unique():
    pct = fairprice._percentile_midrank(90_000, [50_000, 60_000, 70_000, 80_000, 90_000])
    assert pct == 90  # midrank = 4.5


def test_percentile_middle():
    pct = fairprice._percentile_midrank(70_000, [50_000, 60_000, 70_000, 80_000, 90_000])
    assert pct == 50  # midrank = 2.5


def test_percentile_all_tied_returns_50():
    """All comps and target at the same price → 50th percentile (middle of pack)."""
    pct = fairprice._percentile_midrank(60_000, [60_000, 60_000, 60_000, 60_000, 60_000])
    assert pct == 50


def test_percentile_clamps_to_99():
    """Even an extreme outlier should never exceed the schema's CHECK ceiling of 99."""
    pct = fairprice._percentile_midrank(1_000_000, [50_000])
    assert pct <= 99


# ---- compute_percentile ---------------------------------------------------

def test_strict_tier_used_when_5_strict_comps_exist(conn):
    """5 listings within year ±1 and mileage ±15k → strict tier."""
    _add_listing(conn, "T_____TARGET_____", year=2025, mileage=15000, price=70000)
    _add_listing(conn, "C1_______________", year=2025, mileage=10000, price=60000)
    _add_listing(conn, "C2_______________", year=2024, mileage=12000, price=65000)
    _add_listing(conn, "C3_______________", year=2025, mileage=20000, price=75000)
    _add_listing(conn, "C4_______________", year=2024, mileage=8000,  price=80000)
    # 5 records total (target + 4) — that's still <5 comps. Add one more.
    _add_listing(conn, "C5_______________", year=2025, mileage=5000,  price=72000)

    pct, tier = fairprice.compute_percentile(conn, "T_____TARGET_____")
    assert tier == "strict"
    assert pct is not None
    # Target $70k: in [60, 65, 70, 72, 75, 80] → midrank 2.5/6 ≈ 42
    assert 35 <= pct <= 50


def test_falls_back_to_loose_when_strict_thin(conn):
    """Strict tier yields <5; loose tier yields ≥5 → use loose."""
    # Target year=2025 mileage=15000.
    _add_listing(conn, "T_____TARGET_____", year=2025, mileage=15000, price=70000)
    # 1 strict comp (year=2024 mileage=20000 → both windows OK)
    _add_listing(conn, "STRICT___________", year=2024, mileage=20000, price=68000)
    # 5 loose-only comps (year=2023 → outside ±1 but within ±2; mileage within 25k)
    for i in range(5):
        _add_listing(
            conn, f"LOOSE_{i:011d}",
            year=2023, mileage=15000 + 20000, price=60000 + i * 1000,
        )

    pct, tier = fairprice.compute_percentile(conn, "T_____TARGET_____")
    assert tier == "loose"
    assert pct is not None


def test_falls_back_to_broad_when_loose_thin(conn):
    """Both strict and loose <5; broad ≥5 → use broad."""
    _add_listing(conn, "T_____TARGET_____", year=2025, mileage=15000, price=70000)
    # 1 strict
    _add_listing(conn, "STRICT0__________", year=2025, mileage=15000, price=68000)
    # 1 loose-only (year=2023)
    _add_listing(conn, "LOOSE0___________", year=2023, mileage=15000, price=66000)
    # 5 broad-only (year=2022 → outside ±2, within ±3; mileage within ±40k)
    for i in range(5):
        _add_listing(
            conn, f"BROAD_{i:011d}",
            year=2022, mileage=15000 + 35000, price=50000 + i * 1000,
        )

    pct, tier = fairprice.compute_percentile(conn, "T_____TARGET_____")
    assert tier == "broad"
    assert pct is not None


def test_returns_none_when_all_tiers_thin(conn):
    """Insufficient comps in every tier → (None, None)."""
    _add_listing(conn, "T_____TARGET_____", year=2025, mileage=15000, price=70000)
    # Only 2 other cars total
    _add_listing(conn, "OTHER1___________", year=2025, mileage=14000, price=68000)
    _add_listing(conn, "OTHER2___________", year=2025, mileage=16000, price=69000)

    pct, tier = fairprice.compute_percentile(conn, "T_____TARGET_____")
    assert pct is None
    assert tier is None


def test_excludes_gone_listings_from_comps(conn):
    """A 'gone' listing is stale data; do not include in comp pool."""
    _add_listing(conn, "T_____TARGET_____", year=2025, mileage=15000, price=70000)
    # 4 active strict comps
    for i in range(4):
        _add_listing(conn, f"ACTIVE_{i:010d}",
                     year=2025, mileage=15000 + i * 1000, price=60000 + i * 1000)
    # 1 'gone' that would be a strict comp if active
    _add_listing(conn, "GONE_____________",
                 year=2025, mileage=15000, price=99999, status="gone")
    # That gives only 4 strict comps + target = 5 in pool. <5 NON-target comps.
    # Wait: MIN_COMPS = 5 means total pool size including target ≥5.
    # 4 active + target = 5 → strict tier qualifies.
    pct, tier = fairprice.compute_percentile(conn, "T_____TARGET_____")
    assert tier == "strict"
    # The $99,999 GONE listing must not influence the percentile.
    assert pct is not None
    # Pool: [60k, 61k, 62k, 63k, 70k] — target most expensive of 5, midrank 4.5/5 = 90
    assert pct == 90


def test_returns_none_for_unknown_vin(conn):
    pct, tier = fairprice.compute_percentile(conn, "UNKNOWN__________")
    assert pct is None and tier is None


def test_returns_none_for_listing_with_no_price(conn):
    """If price_history is empty for the VIN, fair_price is unknowable."""
    conn.execute(
        "INSERT INTO listings (vin, first_seen, last_seen, status, "
        "year, trim, body_style, mileage_first_seen) "
        "VALUES (?, ?, ?, 'active', 2025, 'E450S4', 'WGN', 15000)",
        ("NOPRICE__________", T0, T0),
    )
    pct, tier = fairprice.compute_percentile(conn, "NOPRICE__________")
    assert pct is None and tier is None


# ---- recompute_all --------------------------------------------------------

def test_recompute_all_updates_active_listings(conn):
    # Build a 6-car cluster of strict-comparable listings
    for i, price in enumerate([60_000, 65_000, 70_000, 75_000, 80_000, 85_000]):
        _add_listing(conn, f"V_{i:015d}", year=2025, mileage=15000, price=price)

    stats = fairprice.recompute_all(conn)
    conn.commit()

    assert stats["total"] == 6
    assert stats["strict"] == 6
    assert stats["insufficient"] == 0

    rows = conn.execute(
        "SELECT vin, fair_price_pct, fair_price_tier FROM listings ORDER BY vin"
    ).fetchall()
    for row in rows:
        assert row["fair_price_tier"] == "strict"
        assert row["fair_price_pct"] is not None


def test_recompute_all_skips_gone_listings(conn):
    _add_listing(conn, "ACTIVE___________", year=2025, mileage=15000, price=70000)
    _add_listing(conn, "GONE_____________", year=2025, mileage=15000, price=70000, status="gone")

    fairprice.recompute_all(conn)
    conn.commit()

    gone = conn.execute(
        "SELECT fair_price_pct, fair_price_tier FROM listings WHERE vin = 'GONE_____________'"
    ).fetchone()
    # 'gone' listings are not touched — fair_price_pct stays whatever it was (NULL for fresh).
    assert gone["fair_price_pct"] is None
    assert gone["fair_price_tier"] is None


# ---- format_percentile ----------------------------------------------------

def test_format_percentile_insufficient():
    assert fairprice.format_percentile(None, None) == "fair price: insufficient comps"


def test_format_percentile_includes_tier_and_relative_phrasing():
    s = fairprice.format_percentile(23, "loose")
    assert "23rd" in s
    assert "loose" in s
    assert "77% of comparable cars" in s


def test_format_percentile_handles_teen_ordinals():
    """11/12/13 take 'th', not 'st/nd/rd' — verify the special case."""
    assert "11th" in fairprice.format_percentile(11, "broad")
    assert "12th" in fairprice.format_percentile(12, "broad")
    assert "13th" in fairprice.format_percentile(13, "broad")


def test_format_percentile_handles_first_second_third():
    assert "1st" in fairprice.format_percentile(1, "strict")
    assert "2nd" in fairprice.format_percentile(2, "strict")
    assert "3rd" in fairprice.format_percentile(3, "strict")


# ---- migration 004 (smoke) -----------------------------------------------

def test_fair_price_columns_exist_on_listings(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    assert "fair_price_pct" in cols
    assert "fair_price_tier" in cols


def test_fair_price_pct_check_constraint(conn):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO listings (vin, first_seen, last_seen, status, fair_price_pct) "
            "VALUES ('X', ?, ?, 'active', 100)", (T0, T0),
        )


def test_fair_price_tier_check_constraint(conn):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO listings (vin, first_seen, last_seen, status, fair_price_tier) "
            "VALUES ('X', ?, ?, 'active', 'invalid')", (T0, T0),
        )
