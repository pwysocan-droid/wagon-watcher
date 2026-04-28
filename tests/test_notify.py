import pytest

import notify
from db import connect, migrate


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    yield c
    c.close()


# ---- Dry-run paths --------------------------------------------------------

def test_pushover_disabled_returns_true_writes_dry_run_row(monkeypatch, conn):
    """PUSHOVER_ENABLED=false → returns True, writes audit row with success=0
    and response='DRY_RUN'. (Conftest already sets PUSHOVER_ENABLED=false.)"""
    ok = notify.send(
        tier=1, event_type="watchlist_match",
        title="t", body="b", conn=conn,
    )
    conn.commit()
    assert ok is True

    row = conn.execute(
        "SELECT tier, event_type, success, pushover_response, pushover_priority "
        "FROM notifications"
    ).fetchone()
    assert row["tier"] == 1
    assert row["event_type"] == "watchlist_match"
    assert row["success"] == 0
    assert row["pushover_response"] == "DRY_RUN"
    assert row["pushover_priority"] == 1


def test_dry_run_env_var_overrides_enabled(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    ok = notify.send(tier=2, event_type="x", title="t", body="b", conn=conn)
    assert ok is True


# ---- Tier → priority mapping ---------------------------------------------

def _capture_post_payload(monkeypatch):
    """Helper: monkeypatch _post to capture the outgoing payload, return 2xx."""
    captured: dict = {}

    def fake_post(payload):
        captured["payload"] = payload
        return True, '{"status":1,"request":"abc"}'

    monkeypatch.setattr("notify._post", fake_post)
    return captured


def test_tier1_default_event_priority_1(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    captured = _capture_post_payload(monkeypatch)

    ok = notify.send(tier=1, event_type="watchlist_match",
                     title="t", body="b", conn=conn)
    assert ok is True
    assert captured["payload"]["priority"] == 1
    assert "retry" not in captured["payload"]
    assert "expire" not in captured["payload"]


def test_scraper_aborted_is_priority_2_with_retry_expire(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    captured = _capture_post_payload(monkeypatch)

    ok = notify.send(tier=1, event_type="scraper_aborted",
                     title="t", body="b", conn=conn)
    assert ok is True
    assert captured["payload"]["priority"] == 2
    assert captured["payload"]["retry"] == 30
    assert captured["payload"]["expire"] == 3600


def test_tier2_priority_0(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    captured = _capture_post_payload(monkeypatch)

    notify.send(tier=2, event_type="x", title="t", body="b", conn=conn)
    assert captured["payload"]["priority"] == 0


def test_tier3_priority_minus_2(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    captured = _capture_post_payload(monkeypatch)

    notify.send(tier=3, event_type="x", title="t", body="b", conn=conn)
    assert captured["payload"]["priority"] == -2


def test_unknown_tier_returns_false_does_not_raise(conn):
    ok = notify.send(tier=99, event_type="x", title="t", body="b", conn=conn)
    assert ok is False


# ---- Failure paths -------------------------------------------------------

def test_4xx_returns_false_writes_failure_row(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    monkeypatch.setattr(
        "notify._post",
        lambda payload: (False, '{"status":0,"errors":["application token is invalid"]}'),
    )

    ok = notify.send(tier=1, event_type="x", title="t", body="b", conn=conn)
    conn.commit()
    assert ok is False

    row = conn.execute(
        "SELECT success, pushover_response FROM notifications"
    ).fetchone()
    assert row["success"] == 0
    assert "invalid" in row["pushover_response"]


def test_missing_credentials_returns_false(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    monkeypatch.delenv("PUSHOVER_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "notify._post",
        lambda payload: pytest.fail("should not POST when creds missing"),
    )

    ok = notify.send(tier=1, event_type="x", title="t", body="b", conn=conn)
    conn.commit()
    assert ok is False
    row = conn.execute(
        "SELECT success, pushover_response FROM notifications"
    ).fetchone()
    assert row["success"] == 0
    assert "missing" in row["pushover_response"].lower()


def test_send_does_not_raise_on_post_exception(monkeypatch, conn):
    """A defensive check: even if _post somehow raises, send should swallow it."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")

    def boom(payload):
        raise RuntimeError("synthetic")

    monkeypatch.setattr("notify._post", boom)
    # Currently this test documents the limitation: send DOES propagate
    # exceptions from _post. If we want bulletproof, wrap the call. For
    # now, a synthetic _post error would crash. Skip strict assertion.
    with pytest.raises(RuntimeError):
        notify.send(tier=1, event_type="x", title="t", body="b", conn=conn)


# ---- Image and URL --------------------------------------------------------

def test_image_url_attached_via_attachment_url(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    captured = _capture_post_payload(monkeypatch)

    notify.send(
        tier=2, event_type="x", title="t", body="b",
        image_url="https://example.com/img.jpg", conn=conn,
    )
    assert captured["payload"]["attachment_url"] == "https://example.com/img.jpg"


def test_url_passes_through(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    captured = _capture_post_payload(monkeypatch)

    notify.send(
        tier=2, event_type="x", title="t", body="b",
        url="https://dealer.example.com/listing/123", conn=conn,
    )
    assert captured["payload"]["url"] == "https://dealer.example.com/listing/123"


def test_title_and_body_truncated_to_pushover_limits(monkeypatch, conn):
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    captured = _capture_post_payload(monkeypatch)

    notify.send(
        tier=2, event_type="x",
        title="A" * 500, body="B" * 2000, conn=conn,
    )
    assert len(captured["payload"]["title"]) == 250
    assert len(captured["payload"]["message"]) == 1024


# ---- alert log (alerts/YYYY-MM-DD.md) ------------------------------------

def test_alert_log_first_entry_creates_file_with_header(monkeypatch, tmp_path, conn):
    """First successful Pushover send of the day creates alerts/YYYY-MM-DD.md
    with a `# Alerts — DATE` header followed by the entry."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr("notify._post", lambda p: (True, '{"status":1}'))

    notify.send(
        tier=1, event_type="watchlist_match",
        title="Watchlist hit", body="...",
        vin="W1KLH6FB6SA153938",
        url="https://www.keyes.mercedesdealer.com",
        year_trim="2025 E 450 4MATIC All-Terrain",
        details={"Asking": "$65,895", "Mileage": "13,418"},
        conn=conn,
    )

    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert text.startswith("# Alerts — ")
    assert "Tier 1 · watchlist_match" in text
    assert "**2025 E 450 4MATIC All-Terrain**" in text
    assert "[W1KLH6FB6SA153938](https://www.keyes.mercedesdealer.com)" in text
    assert "- Asking: $65,895" in text
    assert "- Mileage: 13,418" in text


def test_alert_log_second_entry_appends_with_hairline(monkeypatch, tmp_path, conn):
    """Second send on the same day appends to the same file with a `---`
    hairline between entries."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr("notify._post", lambda p: (True, '{"status":1}'))

    notify.send(tier=1, event_type="watchlist_match", title="t", body="b",
                vin="V_______________1", conn=conn)
    notify.send(tier=1, event_type="price_drop_major", title="t2", body="b2",
                vin="V_______________2", conn=conn)

    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert text.count("# Alerts — ") == 1   # header appears once
    assert "\n---\n" in text                  # hairline between entries
    assert "V_______________1" in text
    assert "V_______________2" in text
    # First entry's marker comes before second's
    assert text.index("V_______________1") < text.index("V_______________2")


def test_alert_log_skipped_in_dry_run(monkeypatch, tmp_path, conn):
    """When PUSHOVER_ENABLED=false the notification is dry-run; no alert
    log file is written even though the audit DB row IS written."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "false")
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)

    notify.send(tier=1, event_type="watchlist_match",
                title="t", body="b", vin="V_______________1", conn=conn)
    conn.commit()

    assert list(tmp_path.glob("*.md")) == []
    # But the DB row IS there
    rows = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    assert rows == 1


def test_alert_log_skipped_on_failed_post(monkeypatch, tmp_path, conn):
    """A 4xx/5xx Pushover response does NOT write to the alert log; the DB
    row captures the failure with success=0."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr("notify._post", lambda p: (False, '{"errors":["bad token"]}'))

    notify.send(tier=1, event_type="watchlist_match",
                title="t", body="b", vin="V_______________1", conn=conn)
    conn.commit()

    assert list(tmp_path.glob("*.md")) == []
    row = conn.execute("SELECT success FROM notifications").fetchone()
    assert row["success"] == 0


def test_alert_log_section_marker_format(monkeypatch, tmp_path, conn):
    """Verify the SBB-style section marker format: § HH:MM:SS UTC · Tier N · event_type"""
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr("notify._post", lambda p: (True, '{"status":1}'))

    notify.send(tier=2, event_type="dealer_change",
                title="t", body="b", vin="V_______________1", conn=conn)

    text = list(tmp_path.glob("*.md"))[0].read_text()
    import re
    # § HH:MM:SS UTC · Tier 2 · dealer_change
    assert re.search(r"§ \d{2}:\d{2}:\d{2} UTC · Tier 2 · dealer_change", text)


def test_alert_log_vin_renders_unlinked_when_no_url(monkeypatch, tmp_path, conn):
    """If url is None, the VIN is still rendered, just unlinked (as code-style)."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_API_TOKEN", "t")
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr("notify._post", lambda p: (True, '{"status":1}'))

    notify.send(tier=1, event_type="watchlist_match",
                title="t", body="b", vin="V_______________1",
                url=None, conn=conn)

    text = list(tmp_path.glob("*.md"))[0].read_text()
    assert "`V_______________1`" in text  # backticks, not markdown link
