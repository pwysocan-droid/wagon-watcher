import json
from datetime import datetime, timezone

import pytest

from db import connect, migrate
from run import commit_message, main, write_latest_json
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


# ---- main() in DRY_RUN ---------------------------------------------------

def test_main_dry_run_rolls_back(monkeypatch, tmp_path):
    """DRY_RUN reads fixture and runs the full pipeline but rolls back the DB."""
    monkeypatch.setenv("DRY_RUN", "1")
    db_path = tmp_path / "inventory.db"
    snapshots = tmp_path / "raw_snapshots"
    latest = tmp_path / "latest.json"
    commit_msg = tmp_path / ".run-commit-msg.txt"

    rc = main(db_path=db_path, snapshots_dir=snapshots,
              latest_json=latest, commit_msg_file=commit_msg)

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
              latest_json=latest, commit_msg_file=commit_msg)

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
               latest_json=latest, commit_msg_file=commit_msg)
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
               latest_json=latest, commit_msg_file=commit_msg)
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
