import json
from datetime import datetime, timezone

import pytest

from db import connect, migrate
from run import commit_message, main, write_latest_json, write_price_history_json
from scrape import ParsedRecord


def _record(vin: str, **overrides):
    base = ParsedRecord(
        vin=vin, year=2025, model="E 450 4MATIC All-Terrain",
        trim="E450S4", body_style="WGN", mbusa_price=70000, mileage=15000,
        exterior_color="Polar White", exterior_color_code="WHT",
        interior_color="Black leather", engine="3.0L",
        is_certified=True, dealer_id="05400", dealer_name="Keyes",
        dealer_zip="91401", dealer_state="CA", dealer_distance_miles=9.7,
        dealer_site_url=None, photo_url=None,
        stock_id="X", options_json=None,
    )
    from dataclasses import replace
    return replace(base, **overrides)


# ---- commit_message format -----------------------------------------------

def test_commit_message_ok():
    when = datetime(2026, 4, 26, 15, 42, tzinfo=timezone.utc)
    result = {
        "status": "ok",
        "aborted_reason": None,
        "stats": {"listings_found": 36, "new_count": 1, "changed_count": 2,
                  "gone_count": 0, "reappeared_count": 1, "duration_ms": 0},
    }
    msg = commit_message(result, when)
    assert msg == ("data: 2026-04-26T15:42Z [36 listings | "
                   "new=1 changed=2 gone=0 reappeared=1]")


def test_commit_message_aborted():
    when = datetime(2026, 4, 26, 15, 42, tzinfo=timezone.utc)
    result = {
        "status": "aborted",
        "aborted_reason": "listings_found=0; last successful run had 36.",
        "stats": {"listings_found": 0, "new_count": 0, "changed_count": 0,
                  "gone_count": 0, "reappeared_count": 0, "duration_ms": 0},
    }
    msg = commit_message(result, when)
    assert "[ABORTED" in msg
    assert "2026-04-26T15:42Z" in msg


# ---- write_latest_json --------------------------------------------------

def test_latest_json_includes_active_excludes_gone(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)

    from reconcile import reconcile
    rs = [_record(f"V{i:017d}") for i in range(5)]
    reconcile(rs, conn, now=datetime(2026, 4, 26, tzinfo=timezone.utc))
    # Drop one in a later run; it'll be marked 'gone'.
    reconcile(rs[1:], conn, now=datetime(2026, 4, 26, 1, tzinfo=timezone.utc))

    out = write_latest_json(conn, tmp_path / "latest.json")
    data = json.loads(out.read_text())

    assert data["count"] == 4
    vins = {r["vin"] for r in data["listings"]}
    assert rs[0].vin not in vins  # 'gone' VIN is filtered out
    assert all(r.vin in vins for r in rs[1:])
    conn.close()


def test_latest_json_has_generated_at(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    out = write_latest_json(conn, tmp_path / "latest.json")
    data = json.loads(out.read_text())
    # Parse it back — must be a valid ISO timestamp
    datetime.fromisoformat(data["generated_at"])
    assert data["count"] == 0
    assert data["listings"] == []
    conn.close()


def test_latest_json_has_kpis_block(tmp_path):
    """Dashboard payload must include KPIs even on an empty DB."""
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    out = write_latest_json(conn, tmp_path / "latest.json")
    data = json.loads(out.read_text())
    kpis = data["kpis"]
    assert kpis["national_pool"] == 0
    assert kpis["within_criteria"] == 0
    assert kpis["median_asking"] is None
    assert kpis["tier1_alerts_7d"] == 0
    conn.close()


def test_latest_json_per_listing_dashboard_fields(tmp_path):
    """Each listing carries the fields the dashboard renders."""
    from datetime import timezone as _tz, datetime as _dt
    conn = connect(tmp_path / "test.db")
    migrate(conn)

    from reconcile import reconcile
    rs = [_record(f"V{i:017d}", year=2025, mileage=15000, mbusa_price=70000)
          for i in range(3)]
    reconcile(rs, conn, now=_dt(2026, 4, 28, tzinfo=_tz.utc))

    out = write_latest_json(conn, tmp_path / "latest.json")
    data = json.loads(out.read_text())
    listing = data["listings"][0]

    # Old fields preserved
    assert listing["vin"]
    assert listing["status"] == "active"
    # New fields for dashboard rendering
    assert listing["current_price"] == 70000
    assert "days_on_lot" in listing
    assert "is_watchlist_match" in listing
    assert "tier1_count" in listing
    assert listing["mbusa_listing_url"].endswith(listing["vin"])
    conn.close()


def test_latest_json_within_criteria_kpi_uses_watchlist(tmp_path):
    """A listing matching the seeded watchlist increments within_criteria."""
    from datetime import timezone as _tz, datetime as _dt
    conn = connect(tmp_path / "test.db")
    migrate(conn)

    from reconcile import reconcile
    # Seed spec: trim=E450S4, body=WGN, year≥2024, mileage≤15000, max_price=68000
    matching = _record("V________________1",
                       year=2025, mileage=10000, mbusa_price=65000)
    not_matching = _record("V________________2",
                           year=2023, mileage=10000, mbusa_price=65000)
    reconcile([matching, not_matching], conn,
              now=_dt(2026, 4, 28, tzinfo=_tz.utc))

    out = write_latest_json(conn, tmp_path / "latest.json")
    data = json.loads(out.read_text())
    assert data["kpis"]["within_criteria"] == 1
    by_vin = {l["vin"]: l for l in data["listings"]}
    assert by_vin["V________________1"]["is_watchlist_match"] is True
    assert by_vin["V________________2"]["is_watchlist_match"] is False
    conn.close()


def test_latest_json_median_asking_kpi(tmp_path):
    """KPI's median_asking is the median of current prices."""
    from datetime import timezone as _tz, datetime as _dt
    conn = connect(tmp_path / "test.db")
    migrate(conn)

    from reconcile import reconcile
    prices = [60000, 65000, 70000, 75000, 80000]
    rs = [_record(f"V{i:017d}", mbusa_price=p) for i, p in enumerate(prices)]
    reconcile(rs, conn, now=_dt(2026, 4, 28, tzinfo=_tz.utc))

    out = write_latest_json(conn, tmp_path / "latest.json")
    data = json.loads(out.read_text())
    assert data["kpis"]["median_asking"] == 70000  # middle of [60,65,70,75,80]
    conn.close()


# ---- write_price_history_json --------------------------------------------

def test_price_history_empty_db_produces_empty_vins(tmp_path):
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    out = write_price_history_json(conn, tmp_path / "price_history.json")
    data = json.loads(out.read_text())
    assert data["schema_version"] == 1
    assert data["vins"] == {}
    datetime.fromisoformat(data["generated_at"])  # valid ISO
    conn.close()


def test_price_history_single_vin_three_observations_correct_stats(tmp_path):
    """One VIN, three price drops over time → observations + stats math."""
    from dataclasses import replace
    from datetime import timezone as _tz, datetime as _dt, timedelta as _td
    from reconcile import reconcile

    conn = connect(tmp_path / "test.db")
    migrate(conn)

    t0 = _dt(2026, 4, 1, tzinfo=_tz.utc)
    r = _record("V________________1", mbusa_price=70_000)
    reconcile([r], conn, now=t0)
    # Each price change requires 2 confirming polls under the stabilization
    # filter (HANDOFF: defends against the MBUSA flap pattern).
    reconcile([replace(r, mbusa_price=68_000)], conn, now=t0 + _td(days=2))
    reconcile([replace(r, mbusa_price=68_000)], conn, now=t0 + _td(days=2, hours=1))
    reconcile([replace(r, mbusa_price=65_000)], conn, now=t0 + _td(days=4))
    reconcile([replace(r, mbusa_price=65_000)], conn, now=t0 + _td(days=4, hours=1))

    out = write_price_history_json(conn, tmp_path / "price_history.json")
    data = json.loads(out.read_text())

    rec = data["vins"]["V________________1"]
    assert len(rec["observations"]) == 3
    prices = [o["price"] for o in rec["observations"]]
    assert prices == [70_000, 68_000, 65_000]
    assert rec["current_price"] == 65_000
    assert rec["status"] == "active"
    assert rec["stats"]["all_time_high"] == 70_000
    assert rec["stats"]["all_time_low"] == 65_000
    assert rec["stats"]["n_observations"] == 3
    # (65000 - 70000) / 70000 * 100 ≈ -7.14%
    assert rec["stats"]["total_drop_pct"] == pytest.approx(-7.14, abs=0.01)
    conn.close()


def test_price_history_excludes_old_gone_vins(tmp_path):
    """Per HANDOFF retention: gone VINs older than 30 days are dropped from
    the export. Recent gone VINs and active VINs always make the cut."""
    from datetime import timezone as _tz, datetime as _dt, timedelta as _td
    from reconcile import reconcile

    conn = connect(tmp_path / "test.db")
    migrate(conn)

    long_ago = _dt(2026, 1, 1, tzinfo=_tz.utc)
    recent = _dt(2026, 4, 20, tzinfo=_tz.utc)

    # Cold-start with 10 listings on 2026-01-01.
    rs = [_record(f"V{i:017d}", mbusa_price=70_000) for i in range(10)]
    reconcile(rs, conn, now=long_ago)

    # On 2026-04-20, only listings 5-9 are still there. 0-4 go 'gone'.
    reconcile(rs[5:], conn, now=recent)

    # Manually back-date the gone VIN's last_seen so it counts as old.
    conn.execute(
        "UPDATE listings SET last_seen = ?, gone_at = ? WHERE vin = ?",
        (long_ago.isoformat(), long_ago.isoformat(), rs[0].vin),
    )
    conn.commit()

    out = write_price_history_json(conn, tmp_path / "price_history.json")
    data = json.loads(out.read_text())

    # rs[0] last_seen long_ago + status='gone' → excluded
    assert rs[0].vin not in data["vins"]
    # rs[5..9] still active → included
    for r in rs[5:]:
        assert r.vin in data["vins"]
        assert data["vins"][r.vin]["status"] == "active"
    conn.close()


# ---- main() in DRY_RUN ---------------------------------------------------

def test_main_dry_run_rolls_back(monkeypatch, tmp_path):
    """DRY_RUN reads fixture and runs the full pipeline but rolls back the DB."""
    monkeypatch.setenv("DRY_RUN", "1")
    db_path = tmp_path / "inventory.db"
    snapshots = tmp_path / "raw_snapshots"
    latest = tmp_path / "latest.json"
    commit_msg = tmp_path / ".run-commit-msg.txt"

    rc = main(db_path=db_path, snapshots_dir=snapshots,
              latest_json=latest,
              price_history_json=tmp_path / "price_history.json",
              commit_msg_file=commit_msg)

    assert rc == 0
    assert db_path.exists()
    # Snapshot is saved unconditionally — DRY_RUN doesn't cover side files
    assert len(list(snapshots.glob("*.json.gz"))) == 1

    # But the DB is empty: reconcile rolled back
    conn = connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()


def test_main_full_pipeline_writes_to_db(monkeypatch, tmp_path):
    """End-to-end: mock fetch_all (so DRY_RUN doesn't rollback), verify DB state."""
    monkeypatch.delenv("DRY_RUN", raising=False)

    from scrape import FIXTURE
    fixture_payload = json.loads(FIXTURE.read_text())
    monkeypatch.setattr("run.fetch_all", lambda *a, **kw: fixture_payload)

    db_path = tmp_path / "inventory.db"
    snapshots = tmp_path / "raw_snapshots"
    latest = tmp_path / "latest.json"
    commit_msg = tmp_path / ".run-commit-msg.txt"

    rc = main(db_path=db_path, snapshots_dir=snapshots,
              latest_json=latest,
              price_history_json=tmp_path / "price_history.json",
              commit_msg_file=commit_msg)

    assert rc == 0
    assert db_path.exists()
    assert len(list(snapshots.glob("*.json.gz"))) == 1

    msg = commit_msg.read_text().strip()
    assert msg.startswith("data: ")
    assert "[12 listings | new=12" in msg

    data = json.loads(latest.read_text())
    assert data["count"] == 12
    assert all(r["status"] == "active" for r in data["listings"])

    conn = connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 12
        runs = conn.execute("SELECT status FROM runs").fetchall()
        assert [r["status"] for r in runs] == ["ok"]
    finally:
        conn.close()


def test_main_abort_returns_nonzero(monkeypatch, tmp_path):
    """A scrape that drops below 50% of last run aborts and exits 1."""
    monkeypatch.delenv("DRY_RUN", raising=False)

    from scrape import FIXTURE
    fixture_payload = json.loads(FIXTURE.read_text())

    db_path = tmp_path / "inventory.db"
    snapshots = tmp_path / "raw_snapshots"
    latest = tmp_path / "latest.json"
    commit_msg = tmp_path / ".run-commit-msg.txt"

    # First run: 12 records, status='ok'
    monkeypatch.setattr("run.fetch_all", lambda *a, **kw: fixture_payload)
    rc1 = main(db_path=db_path, snapshots_dir=snapshots,
               latest_json=latest,
               price_history_json=tmp_path / "price_history.json",
               commit_msg_file=commit_msg)
    assert rc1 == 0

    # Second run: empty payload — health check trips
    empty = {
        "result": {"pagedVehicles": {
            "records": [], "paging": {"totalCount": 0, "currentOffset": 0,
                                      "currentCount": 0}}, "facets": {}},
        "status": {"code": 200, "ok": True, "tmstmp": "0", "traceId": "x"},
        "messages": [], "success": True,
    }
    monkeypatch.setattr("run.fetch_all", lambda *a, **kw: empty)

    rc2 = main(db_path=db_path, snapshots_dir=snapshots,
               latest_json=latest,
               price_history_json=tmp_path / "price_history.json",
               commit_msg_file=commit_msg)
    assert rc2 == 1

    conn = connect(db_path)
    try:
        runs = conn.execute("SELECT status FROM runs ORDER BY id").fetchall()
        assert [r["status"] for r in runs] == ["ok", "aborted"]
        # Listings table is unchanged — the abort doesn't mark anything 'gone'
        assert conn.execute(
            "SELECT COUNT(*) FROM listings WHERE status='active'"
        ).fetchone()[0] == 12
    finally:
        conn.close()

    assert "[ABORTED" in commit_msg.read_text()
