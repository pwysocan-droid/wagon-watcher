"""Tests for digest.py."""
from datetime import datetime, timedelta, timezone

import pytest

import digest
from db import connect, migrate

NOW = datetime(2026, 5, 3, 16, 0, 0, tzinfo=timezone.utc)  # Sunday 9am PDT
WEEK_AGO = NOW - timedelta(days=7)
TWO_WEEKS_AGO = NOW - timedelta(days=14)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    yield c
    c.close()


def _add_listing(conn, vin, *, year=2025, mileage=15000, dealer="Keyes European, LLC",
                 first_seen=None, status="active"):
    first_seen = first_seen or NOW - timedelta(days=10)
    conn.execute(
        "INSERT INTO listings (vin, first_seen, last_seen, status, year, model, "
        "trim, body_style, dealer_name, mileage_first_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vin, first_seen, NOW, status, year,
         "E 450 4MATIC All-Terrain", "E450S4", "WGN", dealer, mileage),
    )


def _add_price(conn, vin, price, when, mileage=15000):
    conn.execute(
        "INSERT INTO price_history (vin, observed_at, price, mileage) VALUES (?, ?, ?, ?)",
        (vin, when, price, mileage),
    )


def _add_run(conn, started_at, *, new=0, changed=0, gone=0, reappeared=0,
             listings_found=36, status="ok"):
    conn.execute(
        "INSERT INTO runs (started_at, finished_at, listings_found, "
        "new_count, changed_count, gone_count, reappeared_count, "
        "duration_ms, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (started_at, started_at + timedelta(seconds=10), listings_found,
         new, changed, gone, reappeared, 10000, status),
    )


# ---- header / week label -------------------------------------------------

def test_week_label_format():
    label = digest._week_label(NOW)
    assert label == "2026-W18"  # 2026-05-03 falls in ISO week 18


def test_header_includes_week_and_run_count(conn):
    _add_run(conn, WEEK_AGO + timedelta(hours=1))
    _add_run(conn, WEEK_AGO + timedelta(hours=2))
    md = digest._header(NOW, WEEK_AGO, NOW, conn)
    assert "Week 18 — 2026" in md
    assert "2 runs · 2 OK" in md
    assert "Source: nafta-service.mbusa.com" in md


# ---- headline counts -----------------------------------------------------

def test_headline_counts_aggregates_runs(conn):
    _add_run(conn, WEEK_AGO + timedelta(hours=1), new=2, changed=1)
    _add_run(conn, WEEK_AGO + timedelta(hours=2), gone=1, reappeared=1)
    md = digest._headline_counts(conn, WEEK_AGO, NOW)
    assert "| 2 | 1 | 1 | 1 | 0 |" in md
    assert "§ 01 — Headline counts" in md


def test_headline_counts_excludes_aborted_runs(conn):
    _add_run(conn, WEEK_AGO + timedelta(hours=1), new=2, status="ok")
    _add_run(conn, WEEK_AGO + timedelta(hours=2), new=99, status="aborted")
    md = digest._headline_counts(conn, WEEK_AGO, NOW)
    assert "| 2 |" in md  # only the OK run counted
    assert "| 99 |" not in md


def test_headline_counts_includes_drop_total(conn):
    _add_run(conn, WEEK_AGO + timedelta(hours=1))
    _add_listing(conn, "V_______________1", first_seen=TWO_WEEKS_AGO)
    _add_price(conn, "V_______________1", 70000, TWO_WEEKS_AGO)
    _add_price(conn, "V_______________1", 65000, WEEK_AGO + timedelta(hours=2))
    md = digest._headline_counts(conn, WEEK_AGO, NOW)
    assert "$5,000" in md
    assert "1 listing" in md


# ---- price drops section -------------------------------------------------

def test_price_drops_section_lists_top_drops(conn):
    _add_listing(conn, "V_______________1", first_seen=TWO_WEEKS_AGO)
    _add_price(conn, "V_______________1", 70000, TWO_WEEKS_AGO)
    _add_price(conn, "V_______________1", 65000, WEEK_AGO + timedelta(hours=1))  # -7.14%
    _add_listing(conn, "V_______________2", year=2023, first_seen=TWO_WEEKS_AGO)
    _add_price(conn, "V_______________2", 60000, TWO_WEEKS_AGO)
    _add_price(conn, "V_______________2", 58000, WEEK_AGO + timedelta(hours=2))  # -3.33%

    md = digest._price_drops_table(conn, WEEK_AGO, NOW)
    assert "§ 03 — Price drops" in md
    assert "$70,000" in md
    assert "$65,000" in md
    # Largest drop should appear first
    assert md.find("V_______________1") < md.find("V_______________2")


def test_price_drops_section_empty_when_no_drops(conn):
    _add_listing(conn, "V_______________1")
    _add_price(conn, "V_______________1", 70000, WEEK_AGO + timedelta(hours=1))
    md = digest._price_drops_table(conn, WEEK_AGO, NOW)
    assert "_No price drops this week._" in md


def test_price_drops_excludes_increases(conn):
    _add_listing(conn, "V_______________1", first_seen=TWO_WEEKS_AGO)
    _add_price(conn, "V_______________1", 70000, TWO_WEEKS_AGO)
    _add_price(conn, "V_______________1", 75000, WEEK_AGO + timedelta(hours=1))  # +7.14%
    md = digest._price_drops_table(conn, WEEK_AGO, NOW)
    assert "_No price drops this week._" in md


# ---- stalest listings ----------------------------------------------------

def test_stalest_listings_orders_by_first_seen(conn):
    _add_listing(conn, "OLDEST___________", first_seen=NOW - timedelta(days=120))
    _add_price(conn, "OLDEST___________", 50000, NOW - timedelta(days=120))
    _add_listing(conn, "MIDDLE___________", first_seen=NOW - timedelta(days=60))
    _add_price(conn, "MIDDLE___________", 60000, NOW - timedelta(days=60))
    _add_listing(conn, "NEWEST___________", first_seen=NOW - timedelta(days=10))
    _add_price(conn, "NEWEST___________", 70000, NOW - timedelta(days=10))

    md = digest._stalest_listings(conn, NOW)
    assert md.find("OLDEST") < md.find("MIDDLE") < md.find("NEWEST")
    # Days-on-Lot column shows correct counts
    assert "120" in md
    assert "60" in md
    assert "10" in md


def test_stalest_excludes_gone(conn):
    _add_listing(conn, "GONE_____________", first_seen=NOW - timedelta(days=200), status="gone")
    _add_listing(conn, "ACTIVE___________", first_seen=NOW - timedelta(days=10))
    _add_price(conn, "ACTIVE___________", 70000, NOW - timedelta(days=10))
    md = digest._stalest_listings(conn, NOW)
    assert "ACTIVE" in md
    assert "GONE_____________" not in md


# ---- watchlist hits ------------------------------------------------------

def test_watchlist_hits_lists_notifications(conn):
    sent_at = WEEK_AGO + timedelta(hours=2)
    conn.execute(
        "INSERT INTO notifications "
        "(sent_at, tier, event_type, vin, title, body, pushover_priority, success) "
        "VALUES (?, 1, 'watchlist_match', ?, ?, ?, 1, 1)",
        (sent_at, "V_______________1",
         "Watchlist hit: 2025 E450S4 · $65,000",
         "VIN V_______________1\nMatches: Within criteria.md"),
    )
    md = digest._watchlist_hits(conn, WEEK_AGO, NOW)
    assert "Watchlist hit" in md
    assert "V_______________1" in md
    assert "Within criteria.md" in md


def test_watchlist_hits_empty(conn):
    md = digest._watchlist_hits(conn, WEEK_AGO, NOW)
    assert "_No watchlist matches this week._" in md


# ---- generate end-to-end --------------------------------------------------

def test_generate_returns_full_markdown(conn):
    _add_run(conn, WEEK_AGO + timedelta(hours=1), new=1)
    md = digest.generate(conn, when=NOW)

    # Each section header present
    for section in ["§ 01", "§ 02", "§ 03", "§ 04", "§ 05"]:
        assert section in md
    assert "# mb-wagon-watcher · weekly digest" in md
    assert "**Week 18 — 2026**" in md
    assert "digest.py" in md  # footer signature


def test_generate_handles_empty_db(conn):
    """No data anywhere — should not crash, should produce a coherent doc."""
    md = digest.generate(conn, when=NOW)
    assert "Week 18 — 2026" in md
    assert "_No watchlist matches this week._" in md
    assert "_No price drops this week._" in md
    assert "_No active listings._" in md


# ---- file output ---------------------------------------------------------

def test_main_writes_dated_and_latest_files(monkeypatch, tmp_path):
    """main() writes BOTH digest/YYYY-WW.md and digest/LATEST.md with same content."""
    db_path = tmp_path / "inventory.db"
    out_dir = tmp_path / "digest"

    # Need a connect that uses tmp_path
    monkeypatch.setattr("digest.connect", lambda *a, **kw: connect(db_path))

    rc = digest.main(["--out-dir", str(out_dir), "--when", NOW.isoformat()])
    assert rc == 0

    dated = out_dir / "2026-W18.md"
    latest = out_dir / "LATEST.md"
    assert dated.exists()
    assert latest.exists()
    assert dated.read_text() == latest.read_text()
    assert "Week 18 — 2026" in dated.read_text()
