"""Tests for digest_daily.py per HANDOFF_daily_digest.md."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import digest_daily
from db import connect, migrate

NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)


def _record(vin: str, **overrides):
    """Mirror tests/test_reconcile.py's _record helper."""
    from scrape import ParsedRecord
    base = ParsedRecord(
        vin=vin, year=2025, model="E 450 4MATIC All-Terrain",
        trim="E450S4", body_style="WGN", mbusa_price=70_000, mileage=15_000,
        exterior_color="Polar White", exterior_color_code="WHT",
        interior_color="Black leather", engine="3.0L",
        is_certified=True, dealer_id="05400", dealer_name="Keyes",
        dealer_zip="91401", dealer_state="CA", dealer_distance_miles=9.7,
        dealer_site_url=None, photo_url=None,
        stock_id="X", options_json=None,
    )
    return replace(base, **overrides)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def empty_config_dir(tmp_path):
    """Empty config dir — none of the optional JSONs exist."""
    d = tmp_path / "config"
    d.mkdir()
    return d


# ---- Test 1: empty DB → all-zero counts, no crash ------------------------

def test_empty_db_produces_valid_digest(conn, empty_config_dir):
    md = digest_daily.generate_daily_digest(conn, when=NOW, config_dir=empty_config_dir)
    # All six sections present with markers
    for marker in ["§ Population", "§ Movers", "§ Floor watch",
                   "§ Anomalies", "§ Watchlist matches", "§ Decision queue"]:
        assert marker in md
    # Header + footer
    assert "mb-wagon-watcher · daily digest" in md
    assert "**2026-04-30**" in md
    # Empty-state messages
    assert "0 active" in md
    assert "_No price moves in the last 24 hours._" in md
    assert "_No VINs at their all-time low today._" in md
    assert "_No anomalies detected in the last 24h._" in md
    assert "_No active watchlist matches._" in md
    assert "_No decisions in queue._" in md


# ---- Test 2: synthetic movers → correct sort + 10-row cap ----------------

def test_movers_section_sorted_and_capped(conn):
    """12 VINs with varying % moves in last 24h. Movers section shows top 10
    by absolute %, ordered descending."""
    from reconcile import reconcile

    yesterday = NOW - timedelta(hours=23)
    two_days_ago = NOW - timedelta(hours=48)

    # Cold-start with 12 VINs at $70k two days ago
    rs = [_record(f"V{i:017d}", mbusa_price=70_000) for i in range(12)]
    reconcile(rs, conn, now=two_days_ago)

    # Reconcile each at a different price within the last 24h
    # Mix of up + down moves of varying %
    new_prices = [
        72_000,  # +2.86%
        67_000,  # -4.29%
        77_000,  # +10.00% — biggest mover
        65_000,  # -7.14%
        70_500,  # +0.71% — smallest, should be cut
        69_500,  # -0.71%
        80_000,  # +14.29% — biggest
        60_000,  # -14.29% — biggest tied
        71_000,  # +1.43%
        69_000,  # -1.43%
        73_500,  # +5.00%
        66_500,  # -5.00%
    ]
    moved = [replace(rs[i], mbusa_price=p) for i, p in enumerate(new_prices)]
    reconcile(moved, conn, now=yesterday)

    md = digest_daily._section_movers(conn, NOW)
    lines = [ln for ln in md.splitlines() if ln.startswith("- ")]

    # Capped at 10
    assert len(lines) == 10
    # First entry has the largest abs %; among 14.29%/-14.29% the order
    # depends on insertion id but both should appear in the top 2.
    head_text = "\n".join(lines[:2])
    assert "+14.29%" in head_text or "-14.29%" in head_text


def test_movers_empty_when_no_24h_changes(conn):
    """No price changes → empty-state message."""
    md = digest_daily._section_movers(conn, NOW)
    assert "_No price moves in the last 24 hours._" in md


# ---- Test 3: disqualified VIN → "DISQUALIFIED (reason)" -----------------

def test_watchlist_match_renders_disqualified_status(conn, tmp_path):
    """A VIN matching watchlist + listed in disqualified_vins.json renders
    with 'DISQUALIFIED (reason)' suffix."""
    from reconcile import reconcile

    # Match the seeded watchlist (year≥2024, mileage≤15000, max_price=68000)
    matching = _record("V_______________M1",
                       year=2025, mileage=10_000, mbusa_price=65_000)
    reconcile([matching], conn, now=NOW)

    # Build a config dir with a disqualified entry
    config = tmp_path / "config"
    config.mkdir()
    (config / digest_daily.DISQUALIFIED_VINS_FILE).write_text(
        json.dumps({"V_______________M1": "Carfax flagged"})
    )

    md = digest_daily._section_watchlist_matches(conn, config)
    assert "V_______________M1" in md
    assert "DISQUALIFIED (Carfax flagged)" in md


def test_watchlist_match_renders_annotation_when_not_disqualified(conn, tmp_path):
    from reconcile import reconcile
    matching = _record("V_______________M2",
                       year=2025, mileage=10_000, mbusa_price=65_000)
    reconcile([matching], conn, now=NOW)

    config = tmp_path / "config"
    config.mkdir()
    (config / digest_daily.VIN_ANNOTATIONS_FILE).write_text(
        json.dumps({"V_______________M2": "pending Carfax"})
    )

    md = digest_daily._section_watchlist_matches(conn, config)
    assert "pending Carfax" in md
    assert "DISQUALIFIED" not in md


def test_watchlist_match_bare_line_with_no_config(conn, empty_config_dir):
    from reconcile import reconcile
    matching = _record("V_______________M3",
                       year=2025, mileage=10_000, mbusa_price=65_000)
    reconcile([matching], conn, now=NOW)

    md = digest_daily._section_watchlist_matches(conn, empty_config_dir)
    assert "V_______________M3" in md
    assert "DISQUALIFIED" not in md
    # Format: "- VIN — dealer_loc — $price"
    line = next(ln for ln in md.splitlines()
                if "V_______________M3" in ln)
    assert line.startswith("- ")
    assert "$65,000" in line


# ---- Decision queue -----------------------------------------------------

def test_decision_queue_renders_open_items_with_days_pending(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / digest_daily.DECISION_QUEUE_FILE).write_text(json.dumps([
        {
            "vin": "V________________1",
            "action": "Carfax + window sticker request",
            "opened_at": (NOW - timedelta(days=3)).isoformat(),
            "closed_at": None,
        },
        {
            "vin": "V________________2",
            "action": "first contact",
            "opened_at": (NOW - timedelta(days=5)).isoformat(),
            "closed_at": None,
        },
        {
            "vin": "V________________3",
            "action": "closed already",
            "opened_at": (NOW - timedelta(days=10)).isoformat(),
            "closed_at": (NOW - timedelta(days=2)).isoformat(),
        },
    ]))
    md = digest_daily._section_decision_queue(NOW, config)
    assert "Open decisions today:" in md
    assert "V________________1" in md
    assert "V________________2" in md
    assert "3 days pending" in md
    assert "5 days pending" in md
    assert "V________________3" not in md  # closed → excluded


def test_decision_queue_empty_message(empty_config_dir):
    md = digest_daily._section_decision_queue(NOW, empty_config_dir)
    assert "_No decisions in queue._" in md
    assert "edit `config/decision_queue.json`" in md


# ---- Population: net-since-yesterday ------------------------------------

def test_population_net_change_computed(conn, empty_config_dir):
    from reconcile import reconcile

    two_days = NOW - timedelta(days=2)
    rs = [_record(f"V{i:017d}", mbusa_price=70_000) for i in range(10)]
    reconcile(rs, conn, now=two_days)

    # Drop 2 VINs yesterday → "active" yesterday = 10, "active" today = 8 → net -2
    one_day = NOW - timedelta(hours=23)
    reconcile(rs[:8], conn, now=one_day)

    md = digest_daily._section_population(conn, NOW, empty_config_dir)
    assert "8 active" in md
    # The pool went from 10 (≥yesterday) to 8 (now) → net -2
    assert "-2 net since yesterday" in md


# ---- main(): writes both files ------------------------------------------

def test_main_writes_dated_and_latest(monkeypatch, tmp_path):
    db_path = tmp_path / "inv.db"
    out_dir = tmp_path / "digest" / "daily"
    config = tmp_path / "config"
    config.mkdir()

    monkeypatch.setattr("digest_daily.connect", lambda *a, **kw: connect(db_path))
    rc = digest_daily.main([
        "--out-dir", str(out_dir),
        "--config-dir", str(config),
        "--when", NOW.isoformat(),
    ])
    assert rc == 0

    dated = out_dir / "2026-04-30.md"
    latest = out_dir / "LATEST.md"
    assert dated.exists()
    assert latest.exists()
    assert dated.read_text() == latest.read_text()
    assert "**2026-04-30**" in dated.read_text()
