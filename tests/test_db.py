import sqlite3
from pathlib import Path

import pytest

from db import connect, current_version, latest_version, migrate


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def test_initial_version_is_zero(conn):
    assert current_version(conn) == 0


def test_migrate_up_creates_all_tables(conn):
    migrate(conn)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    expected = {"listings", "price_history", "notes", "runs", "watchlist", "schema_migrations"}
    assert expected.issubset(tables)


def test_migrate_records_version(conn):
    assert migrate(conn) == latest_version()
    assert current_version(conn) == latest_version()


def test_migrate_is_idempotent(conn):
    migrate(conn)
    migrate(conn)
    assert current_version(conn) == latest_version()


def test_migrate_down_to_zero_drops_tables(conn):
    migrate(conn)
    migrate(conn, target=0)
    assert current_version(conn) == 0
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    # schema_migrations remains; data tables are gone
    assert "listings" not in tables
    assert "price_history" not in tables
    assert "schema_migrations" in tables


def test_round_trip_up_down_up(conn):
    migrate(conn)
    migrate(conn, target=0)
    migrate(conn)
    assert current_version(conn) == latest_version()
    # listings table is usable after the round trip
    conn.execute(
        "INSERT INTO listings (vin, first_seen, last_seen, status) "
        "VALUES ('W1KLH6FB6SA000001', '2026-04-26', '2026-04-26', 'active')"
    )
    row = conn.execute("SELECT vin FROM listings").fetchone()
    assert row["vin"] == "W1KLH6FB6SA000001"


def test_listings_status_check_rejects_invalid(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO listings (vin, first_seen, last_seen, status) "
            "VALUES ('TEST123', '2026-04-26', '2026-04-26', 'invalid')"
        )


def test_listings_status_accepts_each_valid_value(conn):
    migrate(conn)
    for i, status in enumerate(("active", "gone", "reappeared")):
        conn.execute(
            "INSERT INTO listings (vin, first_seen, last_seen, status) "
            "VALUES (?, '2026-04-26', '2026-04-26', ?)",
            (f"V{i:017d}", status),
        )


def test_price_history_fk_enforced(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO price_history (vin, observed_at, price, mileage) "
            "VALUES ('NO_SUCH_VIN', '2026-04-26', 70000, 15000)"
        )


def test_price_history_index_exists(conn):
    migrate(conn)
    indexes = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    assert "idx_price_history_vin_observed" in indexes


def test_runs_status_check(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO runs (started_at, status) "
            "VALUES ('2026-04-26', 'bogus')"
        )


def test_watchlist_kind_check(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO watchlist (kind, label, created_at) "
            "VALUES ('bogus', 'x', '2026-04-26')"
        )


def test_watchlist_active_check(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO watchlist (kind, label, created_at, active) "
            "VALUES ('vin', 'x', '2026-04-26', 5)"
        )


def test_watchlist_active_defaults_to_one(conn):
    migrate(conn)
    conn.execute(
        "INSERT INTO watchlist (kind, label, created_at) "
        "VALUES ('vin', 'x', '2026-04-26')"
    )
    row = conn.execute("SELECT active FROM watchlist").fetchone()
    assert row["active"] == 1


def test_wal_mode_enabled(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_foreign_keys_enabled(conn):
    enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert enabled == 1


# ---- migration 002: notifications table -----------------------------------

def test_notifications_table_exists(conn):
    migrate(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "notifications" in tables


def test_notifications_tier_check(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO notifications "
            "(sent_at, tier, event_type, title, body, pushover_priority, success) "
            "VALUES ('2026-04-27', 4, 'x', 't', 'b', 1, 0)"
        )


def test_notifications_success_check(conn):
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO notifications "
            "(sent_at, tier, event_type, title, body, pushover_priority, success) "
            "VALUES ('2026-04-27', 1, 'x', 't', 'b', 1, 5)"
        )


def test_notifications_recent_index_exists(conn):
    migrate(conn)
    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )}
    assert "notifications_recent" in indexes


def test_notifications_down_migration_drops_table(conn):
    migrate(conn)
    migrate(conn, target=1)  # one step before notifications
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "notifications" not in tables


# ---- migration 003: watchlist seed ----------------------------------------

def test_watchlist_seed_inserts_one_row(conn):
    migrate(conn)
    rows = conn.execute(
        "SELECT kind, label, active FROM watchlist WHERE label = 'Within criteria.md'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "spec"
    assert rows[0]["active"] == 1


def test_watchlist_seed_spec_is_valid_json(conn):
    import json as _json
    migrate(conn)
    row = conn.execute(
        "SELECT spec_json FROM watchlist WHERE label = 'Within criteria.md'"
    ).fetchone()
    spec = _json.loads(row["spec_json"])
    assert spec["trim"] == "E450S4"
    assert spec["body_style"] == "WGN"
    assert spec["min_year"] == 2024
    assert spec["max_mileage"] == 15000
    assert spec["max_price_all_in"] == 68000


def test_watchlist_seed_idempotent(conn):
    migrate(conn)
    # Re-running the seed should not duplicate (the up SQL uses NOT EXISTS).
    # Simulate by re-applying just migration 3.
    seed_sql = (Path(__file__).parent.parent / "migrations"
                / "003_watchlist_seed.up.sql").read_text()
    conn.executescript(seed_sql)
    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM watchlist WHERE label = 'Within criteria.md'"
    ).fetchone()
    assert rows["c"] == 1


def test_watchlist_seed_down_migration_removes_row(conn):
    migrate(conn)
    migrate(conn, target=2)  # rolls back the seed only
    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM watchlist WHERE label = 'Within criteria.md'"
    ).fetchone()
    assert rows["c"] == 0
    # But the watchlist table itself should still exist
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "watchlist" in tables


# ---- migration 005: distance_miles column ---------------------------------

def test_distance_miles_column_exists(conn):
    migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    assert "distance_miles" in cols


def test_distance_miles_down_migration_drops_column(conn):
    migrate(conn)
    migrate(conn, target=4)  # rolls back distance_miles only
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    assert "distance_miles" not in cols
    # fair_price columns still there
    assert "fair_price_pct" in cols


# ---- migration 006: cross-source columns ----------------------------------

def test_cross_source_columns_exist(conn):
    migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    assert "dealer_site_price" in cols
    assert "dealer_site_url" in cols
    assert "dealer_site_checked_at" in cols


def test_cross_source_down_migration_drops_only_those(conn):
    migrate(conn)
    migrate(conn, target=5)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    assert "dealer_site_price" not in cols
    assert "dealer_site_url" not in cols
    assert "dealer_site_checked_at" not in cols
    # distance_miles (from migration 005) still there
    assert "distance_miles" in cols
