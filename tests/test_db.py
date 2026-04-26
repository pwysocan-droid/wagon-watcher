import sqlite3

import pytest

from db import connect, current_version, migrate


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
    assert migrate(conn) == 1
    assert current_version(conn) == 1


def test_migrate_is_idempotent(conn):
    migrate(conn)
    migrate(conn)
    assert current_version(conn) == 1


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
    assert current_version(conn) == 1
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
