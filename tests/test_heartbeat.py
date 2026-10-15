"""Tests for the watcher staleness monitor."""
from datetime import datetime, timedelta, timezone

import pytest

import heartbeat
from db import migrate


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    import sqlite3
    c = sqlite3.connect(tmp_path / "t.db")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _run(c, when, status="ok"):
    c.execute(
        "INSERT INTO runs (started_at, finished_at, listings_found, duration_ms, status) "
        "VALUES (?,?,?,?,?)",
        (when.isoformat(), when.isoformat(), 23, 100, status),
    )
    c.commit()


def test_fresh_run_does_not_alert(conn):
    _run(conn, NOW - timedelta(hours=2))
    v = heartbeat.check(conn, now=NOW, stale_after_h=18)
    assert v["stalled"] is False and v["alerted"] is False


def test_stale_run_alerts(conn):
    _run(conn, NOW - timedelta(hours=30))
    v = heartbeat.check(conn, now=NOW, stale_after_h=18)
    assert v["stalled"] is True and v["alerted"] is True
    row = conn.execute(
        "SELECT event_type, tier FROM notifications ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["event_type"] == "watcher_stalled"
    assert row["tier"] == 1


def test_boundary_is_not_stale(conn):
    """Exactly at the threshold is still healthy — alert only past it."""
    _run(conn, NOW - timedelta(hours=18))
    assert heartbeat.check(conn, now=NOW, stale_after_h=18)["alerted"] is False


def _prior_alert(c, when):
    """Insert a stall alert stamped at a controlled time. notify.send()
    stamps sent_at with the real wall clock, so a test that drives the
    cooldown through send() would compare an injected `now` against a real
    timestamp and pass or fail by accident."""
    c.execute(
        "INSERT INTO notifications (sent_at, tier, event_type, title, body, "
        "pushover_priority, success) VALUES (?,1,?,'x','x',1,1)",
        (when.isoformat(), heartbeat.EVENT_TYPE),
    )
    c.commit()


def test_cooldown_suppresses_repeat_alert(conn):
    _run(conn, NOW - timedelta(hours=30))
    _prior_alert(conn, NOW - timedelta(hours=3))
    v = heartbeat.check(conn, now=NOW, stale_after_h=18, cooldown_h=12)
    assert v["stalled"] is True and v["alerted"] is False
    assert v["reason"] == "within cooldown"


def test_alert_repeats_after_cooldown_expires(conn):
    _run(conn, NOW - timedelta(hours=30))
    _prior_alert(conn, NOW - timedelta(hours=13))
    assert heartbeat.check(conn, now=NOW, stale_after_h=18, cooldown_h=12)["alerted"] is True


def test_aborted_runs_do_not_count_as_healthy(conn):
    """An aborted run means the watcher fired but wrote nothing usable —
    it must not reset the staleness clock."""
    _run(conn, NOW - timedelta(hours=30))
    _run(conn, NOW - timedelta(hours=1), status="aborted")
    assert heartbeat.check(conn, now=NOW, stale_after_h=18)["alerted"] is True


def test_empty_db_does_not_alert(conn):
    """A fresh DB has no runs; that is not a stall."""
    v = heartbeat.check(conn, now=NOW, stale_after_h=18)
    assert v["stalled"] is False and v["alerted"] is False


def test_env_var_configures_threshold(conn, monkeypatch):
    monkeypatch.setenv("STALE_AFTER_HOURS", "4")
    _run(conn, NOW - timedelta(hours=6))
    assert heartbeat.check(conn, now=NOW)["alerted"] is True


# ---- cadence (partial degradation) ---------------------------------------

def _runs_every(c, hours, n, status="ok"):
    for i in range(n):
        _run(c, NOW - timedelta(hours=hours * i + 0.5), status=status)


def _prior_cadence_alert(c, when):
    c.execute(
        "INSERT INTO notifications (sent_at, tier, event_type, title, body, "
        "pushover_priority, success) VALUES (?,1,?,'x','x',1,1)",
        (when.isoformat(), heartbeat.CADENCE_EVENT_TYPE),
    )
    c.commit()


def test_healthy_cadence_does_not_alert(conn):
    _runs_every(conn, 1, 24)
    v = heartbeat.check_cadence(conn, now=NOW, min_runs=10)
    assert v["degraded"] is False and v["runs"] == 24


def test_degraded_cadence_alerts_tier1(conn):
    """The 2026-08-27 failure: still running, ~5 runs/day."""
    _runs_every(conn, 5, 5)
    v = heartbeat.check_cadence(conn, now=NOW, min_runs=10, cooldown_h=24)
    assert v["degraded"] is True and v["alerted"] is True and v["runs"] == 5
    row = conn.execute(
        "SELECT event_type, tier FROM notifications ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["event_type"] == "watcher_degraded" and row["tier"] == 1


def test_cadence_counts_only_trailing_24h(conn):
    _runs_every(conn, 1, 9)                       # 9 in window
    _run(conn, NOW - timedelta(hours=30))         # outside window
    assert heartbeat.check_cadence(conn, now=NOW, min_runs=10)["runs"] == 9


def test_cadence_alert_once_per_cooldown(conn):
    _runs_every(conn, 5, 5)
    _prior_cadence_alert(conn, NOW - timedelta(hours=6))
    v = heartbeat.check_cadence(conn, now=NOW, min_runs=10, cooldown_h=24)
    assert v["degraded"] is True and v["alerted"] is False


def test_cadence_alert_repeats_after_cooldown(conn):
    _runs_every(conn, 5, 5)
    _prior_cadence_alert(conn, NOW - timedelta(hours=25))
    assert heartbeat.check_cadence(conn, now=NOW, min_runs=10, cooldown_h=24)["alerted"] is True


def test_cadence_ignores_aborted_runs(conn):
    _runs_every(conn, 1, 20, status="aborted")
    _runs_every(conn, 5, 3)
    assert heartbeat.check_cadence(conn, now=NOW, min_runs=10)["runs"] == 3


def test_cadence_and_stall_cooldowns_are_independent(conn):
    """A recent stall alert must not suppress the degraded alert."""
    _runs_every(conn, 5, 5)
    _prior_alert(conn, NOW - timedelta(hours=1))
    assert heartbeat.check_cadence(conn, now=NOW, min_runs=10, cooldown_h=24)["alerted"] is True


def test_cadence_empty_db_does_not_alert(conn):
    assert heartbeat.check_cadence(conn, now=NOW, min_runs=10)["alerted"] is False
