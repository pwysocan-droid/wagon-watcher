from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from db import connect, migrate
from reconcile import reconcile
from scrape import ParsedRecord


T0 = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


def _record(vin: str, **overrides) -> ParsedRecord:
    base = ParsedRecord(
        vin=vin,
        year=2025,
        model="E 450 4MATIC All-Terrain",
        trim="E450S4",
        body_style="WGN",
        mbusa_price=70000,
        mileage=15000,
        exterior_color="Obsidian Black metallic",
        exterior_color_code="BLK",
        interior_color="Black leather",
        engine="3.0L inline-6 turbo with mild hybrid drive",
        is_certified=True,
        dealer_id="05400",
        dealer_name="Keyes European, LLC",
        dealer_zip="91401",
        dealer_state="CA",
        dealer_distance_miles=9.7,
        dealer_site_url="http://www.keyes.mercedesdealer.com",
        photo_url=None,
        stock_id="SA000000A",
        options_json=None,
    )
    return replace(base, **overrides)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    migrate(c)
    yield c
    c.close()


# ---- empty DB → all new --------------------------------------------------

def test_first_run_inserts_all_as_new(conn):
    records = [_record(f"V{i:017d}") for i in range(5)]
    result = reconcile(records, conn, now=T0)

    assert result["status"] == "ok"
    assert result["stats"]["new_count"] == 5
    assert result["stats"]["gone_count"] == 0
    assert result["stats"]["changed_count"] == 0

    assert {e["type"] for e in result["events"]} == {"new"}
    assert len(result["events"]) == 5

    rows = conn.execute("SELECT vin, status FROM listings").fetchall()
    assert len(rows) == 5
    assert all(row["status"] == "active" for row in rows)

    history = conn.execute("SELECT vin, price, mileage FROM price_history").fetchall()
    assert len(history) == 5


def test_first_run_records_a_runs_row(conn):
    records = [_record(f"V{i:017d}") for i in range(3)]
    result = reconcile(records, conn, now=T0)
    runs = conn.execute("SELECT * FROM runs").fetchall()
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert runs[0]["listings_found"] == 3
    assert runs[0]["new_count"] == 3
    assert runs[0]["id"] == result["run_id"]


# ---- second run, no change ----------------------------------------------

def test_second_run_no_change_emits_no_events(conn):
    records = [_record(f"V{i:017d}") for i in range(3)]
    reconcile(records, conn, now=T0)
    result = reconcile(records, conn, now=T0 + timedelta(minutes=30))

    assert result["status"] == "ok"
    assert result["stats"]["new_count"] == 0
    assert result["stats"]["changed_count"] == 0
    assert result["stats"]["gone_count"] == 0
    assert result["events"] == []

    history_count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert history_count == 3  # no new history rows on a no-op


def test_second_run_updates_last_seen(conn):
    [r] = [_record("V00000000000000001")]
    reconcile([r], conn, now=T0)
    reconcile([r], conn, now=T0 + timedelta(minutes=30))
    row = conn.execute("SELECT first_seen, last_seen FROM listings").fetchone()
    assert row["first_seen"] != row["last_seen"]


# ---- price change ----------------------------------------------------------

def test_price_drop_emits_event_and_appends_history(conn):
    r = _record("V00000000000000001", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    cheaper = replace(r, mbusa_price=65000)
    result = reconcile([cheaper], conn, now=T0 + timedelta(hours=1))

    assert result["stats"]["changed_count"] == 1
    [evt] = [e for e in result["events"] if e["type"] == "price_change"]
    assert evt["old_price"] == 70000
    assert evt["new_price"] == 65000
    assert evt["pct_change"] == pytest.approx(-0.0714, abs=1e-3)

    history = conn.execute(
        "SELECT price FROM price_history ORDER BY observed_at, id"
    ).fetchall()
    assert [h["price"] for h in history] == [70000, 65000]


def test_price_unchanged_no_history_row(conn):
    r = _record("V00000000000000001")
    reconcile([r], conn, now=T0)
    reconcile([r], conn, now=T0 + timedelta(hours=1))
    history = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert history == 1


# ---- mileage anomaly -----------------------------------------------------

def test_mileage_decrease_emits_event(conn):
    r = _record("V00000000000000001", mileage=20000)
    reconcile([r], conn, now=T0)
    fewer = replace(r, mileage=15000)
    result = reconcile([fewer], conn, now=T0 + timedelta(hours=1))
    types = {e["type"] for e in result["events"]}
    assert "mileage_decrease" in types


def test_mileage_increase_no_event(conn):
    r = _record("V00000000000000001", mileage=15000)
    reconcile([r], conn, now=T0)
    more = replace(r, mileage=15500)
    result = reconcile([more], conn, now=T0 + timedelta(hours=1))
    # mileage going up is normal — no special event
    types = {e["type"] for e in result["events"]}
    assert "mileage_decrease" not in types
    # but the price_history row still gets appended because mileage differs
    history = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert history == 2


# ---- dealer change -------------------------------------------------------

def test_dealer_change_emits_event_and_updates_listing(conn):
    r = _record("V00000000000000001", dealer_name="Keyes European, LLC", dealer_zip="91401")
    reconcile([r], conn, now=T0)

    moved = replace(r, dealer_name="Mercedes-Benz of Valencia", dealer_zip="91355")
    result = reconcile([moved], conn, now=T0 + timedelta(days=1))

    [evt] = [e for e in result["events"] if e["type"] == "dealer_change"]
    assert evt["old_dealer_name"] == "Keyes European, LLC"
    assert evt["new_dealer_name"] == "Mercedes-Benz of Valencia"

    row = conn.execute("SELECT dealer_name, dealer_zip FROM listings").fetchone()
    assert row["dealer_name"] == "Mercedes-Benz of Valencia"
    assert row["dealer_zip"] == "91355"


# ---- vanish + reappear ---------------------------------------------------

def test_vin_vanishes_marked_gone(conn):
    r = _record("V00000000000000001")
    other = _record("V00000000000000002")
    reconcile([r, other], conn, now=T0)

    result = reconcile([other], conn, now=T0 + timedelta(hours=1))

    assert result["stats"]["gone_count"] == 1
    [evt] = [e for e in result["events"] if e["type"] == "gone"]
    assert evt["vin"] == "V00000000000000001"

    row = conn.execute("SELECT status, gone_at FROM listings WHERE vin=?", (r.vin,)).fetchone()
    assert row["status"] == "gone"
    assert row["gone_at"] is not None


def test_gone_vin_does_not_re_emit_gone(conn):
    """Once 'gone', a missing VIN doesn't re-fire on every subsequent run."""
    r = _record("V00000000000000001")
    other = _record("V00000000000000002")
    reconcile([r, other], conn, now=T0)
    reconcile([other], conn, now=T0 + timedelta(hours=1))  # marks r 'gone'
    result = reconcile([other], conn, now=T0 + timedelta(hours=2))
    assert result["stats"]["gone_count"] == 0
    assert not any(e["type"] == "gone" for e in result["events"])


def test_gone_vin_reappears(conn):
    r = _record("V00000000000000001")
    other = _record("V00000000000000002")
    reconcile([r, other], conn, now=T0)
    reconcile([other], conn, now=T0 + timedelta(hours=1))  # r gone

    result = reconcile([r, other], conn, now=T0 + timedelta(hours=2))
    assert result["stats"]["reappeared_count"] == 1
    [evt] = [e for e in result["events"] if e["type"] == "reappeared"]
    assert evt["vin"] == r.vin

    row = conn.execute("SELECT status, gone_at FROM listings WHERE vin=?", (r.vin,)).fetchone()
    assert row["status"] == "reappeared"
    assert row["gone_at"] is None


def test_reappeared_promotes_to_active_on_next_sighting(conn):
    """The 'reappeared' tag should not stick on every poll forever."""
    r = _record("V00000000000000001")
    reconcile([r], conn, now=T0)
    reconcile([], conn, now=T0 + timedelta(hours=1))  # vanish — but health check will abort!
    # The above abort means r is not marked gone. Build a different scenario:


def test_reappeared_promotes_to_active(conn):
    # Use enough listings so dropping one doesn't trigger health check
    rs = [_record(f"V{i:017d}") for i in range(10)]
    reconcile(rs, conn, now=T0)
    # Drop the first one — 9 of 10, still above 50%
    reconcile(rs[1:], conn, now=T0 + timedelta(hours=1))  # rs[0] gone

    # rs[0] reappears
    result1 = reconcile(rs, conn, now=T0 + timedelta(hours=2))
    assert result1["stats"]["reappeared_count"] == 1
    row = conn.execute("SELECT status FROM listings WHERE vin=?", (rs[0].vin,)).fetchone()
    assert row["status"] == "reappeared"

    # Same scrape next poll — should transition reappeared → active, no event
    result2 = reconcile(rs, conn, now=T0 + timedelta(hours=3))
    assert result2["stats"]["reappeared_count"] == 0
    assert not any(e["type"] == "reappeared" for e in result2["events"])
    row = conn.execute("SELECT status FROM listings WHERE vin=?", (rs[0].vin,)).fetchone()
    assert row["status"] == "active"


# ---- health check --------------------------------------------------------

def test_zero_listings_aborts(conn):
    result = reconcile([], conn, now=T0)
    assert result["status"] == "aborted"
    assert "listings_found=0" in result["aborted_reason"]
    runs = conn.execute("SELECT status, listings_found FROM runs").fetchall()
    assert len(runs) == 1
    assert runs[0]["status"] == "aborted"
    assert runs[0]["listings_found"] == 0


def test_zero_listings_writes_no_listings(conn):
    reconcile([], conn, now=T0)
    rows = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    assert rows == 0


def test_under_50pct_of_last_run_aborts(conn):
    rs = [_record(f"V{i:017d}") for i in range(20)]
    reconcile(rs, conn, now=T0)

    # Half = 10. Anything <10 should abort.
    result = reconcile(rs[:9], conn, now=T0 + timedelta(hours=1))
    assert result["status"] == "aborted"
    assert "listings_found=9" in result["aborted_reason"]

    # And no listings should have been touched
    counts = conn.execute(
        "SELECT status, COUNT(*) AS c FROM listings GROUP BY status"
    ).fetchall()
    statuses = {r["status"]: r["c"] for r in counts}
    assert statuses == {"active": 20}


def test_exactly_at_threshold_proceeds(conn):
    rs = [_record(f"V{i:017d}") for i in range(20)]
    reconcile(rs, conn, now=T0)
    # 10 of 20 = exactly 50%; threshold is < 50%, so this should proceed
    result = reconcile(rs[:10], conn, now=T0 + timedelta(hours=1))
    assert result["status"] == "ok"


def test_health_check_uses_last_ok_run_not_aborted(conn):
    """An aborted run should not become the baseline for the next health check."""
    rs = [_record(f"V{i:017d}") for i in range(20)]
    reconcile(rs, conn, now=T0)              # ok, baseline=20
    reconcile(rs[:9], conn, now=T0 + timedelta(hours=1))  # aborted (9 < 10)
    # Threshold should still be 0.5 * 20 = 10, not 0.5 * 9 = 4.5.
    # 8 records < 10, so should still abort.
    result = reconcile(rs[:8], conn, now=T0 + timedelta(hours=2))
    assert result["status"] == "aborted"


def test_first_run_skips_threshold_check(conn):
    """No prior runs ⇒ no baseline ⇒ a small first run is allowed."""
    [r] = [_record("V00000000000000001")]
    result = reconcile([r], conn, now=T0)
    assert result["status"] == "ok"


# ---- DRY_RUN -------------------------------------------------------------

def test_dry_run_rolls_back(conn):
    r = _record("V00000000000000001")
    result = reconcile([r], conn, now=T0, dry_run=True)
    assert result["status"] == "ok"
    assert result["stats"]["new_count"] == 1
    # But nothing committed
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_dry_run_env_var(monkeypatch, conn):
    monkeypatch.setenv("DRY_RUN", "1")
    r = _record("V00000000000000001")
    reconcile([r], conn, now=T0)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0


# ---- API-anomaly defenses (price=None, prior price=0) -------------------

def test_new_listing_with_no_price_skips_price_history(conn):
    """A new VIN observed during an API anomaly (price=None) gets a
    listings row but no price_history row. The next poll with a real
    price will start tracking normally."""
    r = _record("V_NEW_NO_PRICE___", mbusa_price=None)
    reconcile([r], conn, now=T0)

    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM price_history WHERE vin=?",
        (r.vin,),
    ).fetchone()[0] == 0


def test_existing_listing_with_no_price_skips_price_history(conn):
    """If an established VIN gets a None price on a poll, skip the price
    insert — don't pollute price_history with NULL or 0."""
    r = _record("V________________1", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    bad = replace(r, mbusa_price=None)
    reconcile([bad], conn, now=T0 + timedelta(hours=1))

    history_count = conn.execute(
        "SELECT COUNT(*) FROM price_history WHERE vin=?", (r.vin,),
    ).fetchone()[0]
    assert history_count == 1  # only the original


def test_recovery_from_zero_prior_counts_change_but_no_event(conn):
    """If a prior price_history row is 0 (legacy anomaly) and a new poll
    brings a real price, count it as a change for runs.changed_count but
    don't emit a price_change event (pct from 0 baseline is meaningless)."""
    # Seed an anomalous row directly.
    r = _record("V________________1", mbusa_price=70000)
    reconcile([r], conn, now=T0)
    conn.execute(
        "INSERT INTO price_history (vin, observed_at, price, mileage) "
        "VALUES (?, ?, 0, 15000)",
        (r.vin, T0 + timedelta(minutes=30)),
    )
    conn.commit()

    calls = []
    import reconcile as recon_mod

    def fake(**kw):
        calls.append(kw)
        return True

    monkeypatch_send = recon_mod.notify.send
    recon_mod.notify.send = fake
    try:
        result = reconcile([r], conn, now=T0 + timedelta(hours=1))
    finally:
        recon_mod.notify.send = monkeypatch_send

    # No price_change event from the bogus 0 baseline → no Tier 1 alert
    assert not any(c.get("event_type") == "price_drop_major" for c in calls)
    # But changed_count > 0 — the recovery IS DB-level activity worth logging
    assert result["stats"]["changed_count"] >= 1


# ---- Tier 1 notification call sites (step 5) ----------------------------

def _capture_notify_calls(monkeypatch):
    """Replace reconcile.notify.send with a recorder; return the list."""
    calls: list[dict] = []

    def fake(**kw):
        calls.append(kw)
        return True

    monkeypatch.setattr("reconcile.notify.send", fake)
    return calls


def test_watchlist_match_fires_tier1_notification(monkeypatch, conn):
    """A NEW listing matching the seeded watchlist spec triggers exactly one
    tier=1 watchlist_match notification.

    The seed (per migration 003): trim=E450S4, body=WGN, year≥2024,
    mileage≤15000, max_price_all_in=68000.
    """
    calls = _capture_notify_calls(monkeypatch)

    matching = _record("V00000000000000001",
                       year=2025, mileage=10000, mbusa_price=65000)
    too_old = _record("V00000000000000002",
                      year=2023, mileage=10000, mbusa_price=65000)
    too_pricey = _record("V00000000000000003",
                         year=2025, mileage=10000, mbusa_price=70000)
    reconcile([matching, too_old, too_pricey], conn, now=T0)

    watchlist_calls = [c for c in calls if c.get("event_type") == "watchlist_match"]
    assert len(watchlist_calls) == 1
    assert watchlist_calls[0]["tier"] == 1
    assert watchlist_calls[0]["vin"] == "V00000000000000001"


def test_watchlist_match_only_on_new_not_repeat_sightings(monkeypatch, conn):
    """A VIN that already exists in listings doesn't re-fire watchlist_match
    on subsequent runs. Tier 1 should fire once per new VIN, not once per poll."""
    calls = _capture_notify_calls(monkeypatch)
    matching = _record("V00000000000000001",
                       year=2025, mileage=10000, mbusa_price=65000)

    reconcile([matching], conn, now=T0)
    reconcile([matching], conn, now=T0 + timedelta(hours=1))

    watchlist_calls = [c for c in calls if c.get("event_type") == "watchlist_match"]
    assert len(watchlist_calls) == 1


def test_price_drop_at_threshold_fires_tier1(monkeypatch, conn):
    """A price drop ≥7% fires Tier 1 price_drop_major. 7.14% is enough."""
    r = _record("V00000000000000001", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    cheaper = replace(r, mbusa_price=65000)  # -7.14%
    reconcile([cheaper], conn, now=T0 + timedelta(hours=1))

    drops = [c for c in calls if c.get("event_type") == "price_drop_major"]
    assert len(drops) == 1
    assert drops[0]["tier"] == 1
    assert drops[0]["vin"] == "V00000000000000001"


def test_price_drop_below_threshold_no_tier1(monkeypatch, conn):
    """A 5% drop does not fire Tier 1 price_drop_major (becomes Tier 2 in step 9)."""
    r = _record("V00000000000000001", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    smaller = replace(r, mbusa_price=66500)  # -5%
    reconcile([smaller], conn, now=T0 + timedelta(hours=1))

    assert not any(c.get("event_type") == "price_drop_major" for c in calls)


def test_price_increase_no_tier1(monkeypatch, conn):
    """A price INCREASE doesn't fire price_drop_major regardless of magnitude."""
    r = _record("V00000000000000001", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    pricier = replace(r, mbusa_price=80000)  # +14%
    reconcile([pricier], conn, now=T0 + timedelta(hours=1))

    assert not any(c.get("event_type") == "price_drop_major" for c in calls)


def test_reappeared_fires_tier1(monkeypatch, conn):
    """A VIN that was 'gone' and shows up again fires Tier 1 reappeared."""
    rs = [_record(f"V{i:017d}") for i in range(10)]
    reconcile(rs, conn, now=T0)
    reconcile(rs[1:], conn, now=T0 + timedelta(hours=1))  # rs[0] marked gone

    calls = _capture_notify_calls(monkeypatch)
    reconcile(rs, conn, now=T0 + timedelta(hours=2))  # rs[0] reappears

    reapp = [c for c in calls if c.get("event_type") == "reappeared"]
    assert len(reapp) == 1
    assert reapp[0]["tier"] == 1
    assert reapp[0]["vin"] == rs[0].vin


def test_gone_does_not_fire_tier1(monkeypatch, conn):
    """A VIN going 'gone' is Tier 3 (silent), not Tier 1."""
    calls = _capture_notify_calls(monkeypatch)
    rs = [_record(f"V{i:017d}") for i in range(10)]
    reconcile(rs, conn, now=T0)
    reconcile(rs[1:], conn, now=T0 + timedelta(hours=1))  # rs[0] marked gone

    assert not any(c.get("tier") == 1 and "gone" in str(c.get("event_type", ""))
                   for c in calls)


# ---- Tier 2 / Tier 3 routing (step 9) ------------------------------------

def test_new_listing_fires_tier2_when_not_watchlist_match(monkeypatch, conn):
    """A new listing that does NOT match the watchlist still fires a
    Tier 2 'new_listing' alert."""
    calls = _capture_notify_calls(monkeypatch)
    over_budget = _record("V________________1",
                          year=2025, mileage=10000, mbusa_price=72000)  # > 68k cap
    reconcile([over_budget], conn, now=T0)

    new_calls = [c for c in calls if c.get("event_type") == "new_listing"]
    assert len(new_calls) == 1
    assert new_calls[0]["tier"] == 2


def test_new_listing_suppressed_when_watchlist_match_fired(monkeypatch, conn):
    """A new listing that matches watchlist (Tier 1) does NOT also fire
    Tier 2 — avoid stacking two alerts for the same VIN/poll."""
    calls = _capture_notify_calls(monkeypatch)
    matching = _record("V________________1",
                       year=2025, mileage=10000, mbusa_price=65000)
    reconcile([matching], conn, now=T0)

    types = {c.get("event_type") for c in calls}
    assert "watchlist_match" in types
    assert "new_listing" not in types


def test_price_drop_in_3_to_7_pct_fires_tier2(monkeypatch, conn):
    """A 5% drop should fire Tier 2 price_drop_minor, not Tier 1, not Tier 3."""
    r = _record("V________________1", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    cheaper = replace(r, mbusa_price=66500)  # -5%
    reconcile([cheaper], conn, now=T0 + timedelta(hours=1))

    types = [c.get("event_type") for c in calls]
    assert "price_drop_minor" in types
    assert "price_drop_major" not in types
    assert "price_drop_silent" not in types


def test_price_drop_under_3_pct_fires_tier3_silent(monkeypatch, conn):
    """A 1% drop should fire Tier 3 price_drop_silent."""
    r = _record("V________________1", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    cheaper = replace(r, mbusa_price=69300)  # -1%
    reconcile([cheaper], conn, now=T0 + timedelta(hours=1))

    silent = [c for c in calls if c.get("event_type") == "price_drop_silent"]
    assert len(silent) == 1
    assert silent[0]["tier"] == 3
    # No Tier 2 from this same drop
    assert not any(c.get("event_type") == "price_drop_minor" for c in calls)


def test_price_drop_over_7_pct_fires_only_tier1(monkeypatch, conn):
    """A 10% drop fires only Tier 1 (price_drop_major); not Tier 2/3 too."""
    r = _record("V________________1", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    cheaper = replace(r, mbusa_price=63000)  # -10%
    reconcile([cheaper], conn, now=T0 + timedelta(hours=1))

    drop_types = [c.get("event_type") for c in calls
                  if c.get("event_type", "").startswith("price_drop_")]
    assert drop_types == ["price_drop_major"]


def test_price_increase_no_notification(monkeypatch, conn):
    """A price INCREASE never fires any tier of price-drop alert."""
    r = _record("V________________1", mbusa_price=70000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    pricier = replace(r, mbusa_price=75000)
    reconcile([pricier], conn, now=T0 + timedelta(hours=1))

    drops = [c for c in calls if "price_drop" in c.get("event_type", "")]
    assert drops == []


def test_dealer_change_fires_tier2(monkeypatch, conn):
    r = _record("V________________1",
                dealer_name="Keyes European, LLC", dealer_zip="91401")
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    moved = replace(r, dealer_name="Mercedes-Benz of Valencia", dealer_zip="91355")
    reconcile([moved], conn, now=T0 + timedelta(hours=1))

    dealer_calls = [c for c in calls if c.get("event_type") == "dealer_change"]
    assert len(dealer_calls) == 1
    assert dealer_calls[0]["tier"] == 2


def test_mileage_decrease_fires_tier2(monkeypatch, conn):
    r = _record("V________________1", mileage=20000)
    reconcile([r], conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    fewer = replace(r, mileage=15000)
    reconcile([fewer], conn, now=T0 + timedelta(hours=1))

    mileage_calls = [c for c in calls if c.get("event_type") == "mileage_anomaly"]
    assert len(mileage_calls) == 1
    assert mileage_calls[0]["tier"] == 2


def test_gone_fires_tier3_silent(monkeypatch, conn):
    """A vanished VIN fires Tier 3 silent."""
    rs = [_record(f"V{i:017d}") for i in range(10)]
    reconcile(rs, conn, now=T0)

    calls = _capture_notify_calls(monkeypatch)
    reconcile(rs[1:], conn, now=T0 + timedelta(hours=1))  # rs[0] marked gone

    gone_calls = [c for c in calls if c.get("event_type") == "gone"]
    assert len(gone_calls) == 1
    assert gone_calls[0]["tier"] == 3
    assert gone_calls[0]["vin"] == rs[0].vin


def test_gone_only_fires_once_not_each_subsequent_poll(monkeypatch, conn):
    """Once 'gone', the VIN doesn't re-fire Tier 3 on every poll thereafter."""
    rs = [_record(f"V{i:017d}") for i in range(10)]
    reconcile(rs, conn, now=T0)
    reconcile(rs[1:], conn, now=T0 + timedelta(hours=1))  # rs[0] gone (Tier 3 fires)

    calls = _capture_notify_calls(monkeypatch)
    reconcile(rs[1:], conn, now=T0 + timedelta(hours=2))
    reconcile(rs[1:], conn, now=T0 + timedelta(hours=3))

    assert not any(c.get("event_type") == "gone" for c in calls)
