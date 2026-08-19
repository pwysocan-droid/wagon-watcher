import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scrape import (
    FIXTURE,
    ParsedRecord,
    fetch_all,
    parse_record,
    parse_response,
    save_snapshot,
)


@pytest.fixture
def payload() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def raw_records(payload) -> list[dict]:
    return payload["result"]["pagedVehicles"]["records"]


def test_fixture_has_twelve_records(raw_records):
    assert len(raw_records) == 12


def test_parse_record_zero_full_mapping(raw_records):
    p = parse_record(raw_records[0])
    assert p.vin == "W1KLH6FB6SA153938"
    assert p.year == 2025
    assert p.model == "E 450 4MATIC All-Terrain"
    assert p.trim == "E450S4"
    assert p.body_style == "WGN"
    assert p.mbusa_price == 65895
    assert p.mileage == 13418
    assert p.exterior_color == "Obsidian Black metallic"
    assert p.exterior_color_code == "BLK"
    assert p.interior_color == "Black leather"
    assert p.engine == "3.0L inline-6 turbo with mild hybrid drive"
    assert p.is_certified is True
    assert p.dealer_id == "05400"
    assert p.dealer_name == "Keyes European, LLC"
    assert p.dealer_zip == "91401"
    assert p.dealer_state == "CA"
    assert p.dealer_distance_miles == pytest.approx(9.7)
    assert p.dealer_site_url == "http://www.keyes.mercedesdealer.com"
    assert p.photo_url and p.photo_url.startswith("https://content.homenetiol.com")
    assert p.stock_id == "SA153938P"
    assert p.options_json is not None
    options = json.loads(p.options_json)
    assert any(o["code"] == "0:04U" for o in options)


def test_parse_record_sparse_record(raw_records):
    """Records 2+ are sparser — no top-level dealer.address, no images, no options."""
    p = parse_record(raw_records[1])
    assert p.vin == "W1KLH6FB0SA134463"
    assert p.dealer_name == "Mercedes-Benz of Valencia"
    assert p.dealer_zip == "91355"
    assert p.dealer_state == "CA"
    assert p.dealer_distance_miles == pytest.approx(32.1)
    assert p.mileage == 12310
    assert p.photo_url is None
    assert p.options_json is None


def test_parse_response_returns_all_twelve(payload):
    records, paging = parse_response(payload)
    assert len(records) == 12
    assert paging["totalCount"] == 53
    assert paging["currentCount"] == 12


def test_parse_response_every_record_has_a_vin(payload):
    records, _ = parse_response(payload)
    vins = {r.vin for r in records}
    assert len(vins) == 12
    for vin in vins:
        assert len(vin) == 17


def test_parse_response_every_record_is_e450s4_wagon(payload):
    records, _ = parse_response(payload)
    for r in records:
        assert r.trim == "E450S4"
        assert r.body_style == "WGN"


def test_parse_response_every_record_is_certified(payload):
    records, _ = parse_response(payload)
    for r in records:
        assert r.is_certified is True


def test_parse_response_raises_on_success_false(payload):
    payload["success"] = False
    payload["messages"] = [{"text": "boom"}]
    with pytest.raises(ValueError, match="success=false"):
        parse_response(payload)


def test_parse_response_raises_on_non_200(payload):
    payload["status"] = {"code": 500}
    with pytest.raises(ValueError, match="status code is 500"):
        parse_response(payload)


def test_parse_record_handles_missing_optional_fields():
    minimal = {"vin": "TESTVIN0000000001", "usedVehicleAttributes": {}}
    p = parse_record(minimal)
    assert p.vin == "TESTVIN0000000001"
    assert p.year is None
    assert p.mileage is None
    assert p.dealer_name is None
    assert p.dealer_zip is None
    assert p.dealer_distance_miles is None
    assert p.photo_url is None
    assert p.options_json is None


def test_parse_record_year_is_cast_to_int(raw_records):
    """Year is a string in JSON — must be cast."""
    p = parse_record(raw_records[0])
    assert isinstance(p.year, int)
    assert p.year == 2025


def test_parse_record_distance_is_cast_to_float(raw_records):
    """Distance is a string in JSON — must be cast."""
    p = parse_record(raw_records[0])
    assert isinstance(p.dealer_distance_miles, float)


def test_parse_record_mileage_is_int_not_float(raw_records):
    """Mileage is a float in JSON; the watcher stores INTEGER. Cast at the boundary."""
    p = parse_record(raw_records[0])
    assert isinstance(p.mileage, int)


def test_parse_record_treats_zero_msrp_as_missing():
    """The MBUSA API has been observed returning msrp=0 transiently.
    CPO wagons are never $0; treat as None so downstream code skips
    pricing operations until the API recovers."""
    raw = {"vin": "ZERO_PRICE_______", "msrp": 0, "usedVehicleAttributes": {"mileage": 12000}}
    p = parse_record(raw)
    assert p.mbusa_price is None
    assert p.mileage == 12000  # unrelated fields still parse


def test_parse_record_treats_negative_msrp_as_missing():
    raw = {"vin": "NEG_PRICE________", "msrp": -1, "usedVehicleAttributes": {}}
    p = parse_record(raw)
    assert p.mbusa_price is None


def test_parse_record_quarantines_price_at_floor_and_logs(tmp_path, monkeypatch):
    """msrp <= PRICE_ANOMALY_FLOOR is treated as missing AND appended to the
    anomalies log — the 2026-04-26 price=0 glitch made it into price_history
    silently; a recurrence must be visible."""
    import scrape
    log = tmp_path / "anomalies.jsonl"
    monkeypatch.setattr(scrape, "ANOMALIES_LOG", log)
    raw = {"vin": "FLOOR_PRICE______", "msrp": scrape.PRICE_ANOMALY_FLOOR,
           "usedVehicleAttributes": {"mileage": 12000}}
    p = parse_record(raw)
    assert p.mbusa_price is None
    assert p.mileage == 12000  # unrelated fields still parse
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["kind"] == "price_quarantined"
    assert entry["vin"] == "FLOOR_PRICE______"
    assert entry["raw_msrp"] == scrape.PRICE_ANOMALY_FLOOR


def test_parse_record_price_just_above_floor_passes_without_logging(
    tmp_path, monkeypatch,
):
    import scrape
    log = tmp_path / "anomalies.jsonl"
    monkeypatch.setattr(scrape, "ANOMALIES_LOG", log)
    raw = {"vin": "OK_PRICE_________",
           "msrp": scrape.PRICE_ANOMALY_FLOOR + 1, "usedVehicleAttributes": {}}
    p = parse_record(raw)
    assert p.mbusa_price == scrape.PRICE_ANOMALY_FLOOR + 1
    assert not log.exists()


def test_parse_record_missing_msrp_does_not_log(tmp_path, monkeypatch):
    """Absent msrp is ordinary sparse data, not an anomaly."""
    import scrape
    log = tmp_path / "anomalies.jsonl"
    monkeypatch.setattr(scrape, "ANOMALIES_LOG", log)
    p = parse_record({"vin": "NO_PRICE_________", "usedVehicleAttributes": {}})
    assert p.mbusa_price is None
    assert not log.exists()


def test_parse_record_handles_dealer_with_no_address():
    raw = {
        "vin": "TESTVIN0000000002",
        "usedVehicleAttributes": {"dealer": {"name": "Solo", "address": []}},
    }
    p = parse_record(raw)
    assert p.dealer_name == "Solo"
    assert p.dealer_zip is None
    assert p.dealer_state is None


def test_fetch_all_dry_run_returns_fixture_payload(payload):
    out = fetch_all(dry_run=True)
    assert out == payload


def test_fetch_all_respects_env_var(monkeypatch, payload):
    monkeypatch.setenv("DRY_RUN", "1")
    out = fetch_all()
    assert out["result"]["pagedVehicles"]["paging"]["totalCount"] == 53
    assert out == payload


def _paged_response(vins: list[str], total: int) -> dict:
    return {
        "result": {"pagedVehicles": {
            "records": [{"vin": v} for v in vins],
            "paging": {"totalCount": total, "currentOffset": 0,
                       "currentCount": len(vins)},
        }, "facets": {}},
        "status": {"code": 200, "ok": True, "tmstmp": "0", "traceId": "x"},
        "messages": [],
        "success": True,
    }


def test_fetch_all_walks_pages_until_short_page(monkeypatch):
    """`start` is a zero-based page index and `count` the page size, so the
    walk must request page 0 first (the nearest cars — the page the old
    count-union strategy never fetched) and stop on the first short page."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    from scrape import PAGE_SIZE

    pages = {
        "0": [f"P0_{i}" for i in range(PAGE_SIZE)],       # full page
        "1": [f"P1_{i}" for i in range(PAGE_SIZE)],       # full page
        "2": [f"P2_{i}" for i in range(5)],               # short → stop
        "3": [],                                          # must not be fetched
    }
    calls: list[tuple[str, str]] = []

    def mock_fetch(query):
        calls.append((query["start"], query["count"]))
        return _paged_response(pages[query["start"]], 29)

    monkeypatch.setattr("scrape._fetch_page", mock_fetch)
    out = fetch_all()

    assert calls == [("0", str(PAGE_SIZE)), ("1", str(PAGE_SIZE)),
                     ("2", str(PAGE_SIZE))]
    vins = [r["vin"] for r in out["result"]["pagedVehicles"]["records"]]
    assert vins[0] == "P0_0"  # page 0 is present, and first
    assert len(vins) == 29
    paging = out["result"]["pagedVehicles"]["paging"]
    assert paging["totalCount"] == 29
    assert paging["currentCount"] == 29


def test_fetch_all_stops_on_empty_page_when_pool_is_a_page_multiple(monkeypatch):
    """A pool that's an exact multiple of PAGE_SIZE ends with an empty page."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    from scrape import PAGE_SIZE

    pages = {"0": [f"A{i}" for i in range(PAGE_SIZE)],
             "1": [f"B{i}" for i in range(PAGE_SIZE)],
             "2": []}
    seen: list[str] = []

    def mock_fetch(query):
        seen.append(query["start"])
        return _paged_response(pages[query["start"]], PAGE_SIZE * 2)

    monkeypatch.setattr("scrape._fetch_page", mock_fetch)
    out = fetch_all()
    assert seen == ["0", "1", "2"]
    assert len(out["result"]["pagedVehicles"]["records"]) == PAGE_SIZE * 2


def test_fetch_all_dedupes_vins_repeated_across_pages(monkeypatch):
    """The page boundary has been observed repeating a record; dedupe by VIN."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    from scrape import PAGE_SIZE

    shared = "SHARED_VIN_0000001"
    pages = {
        "0": [f"A{i}" for i in range(PAGE_SIZE - 1)] + [shared],
        "1": [shared] + [f"B{i}" for i in range(6)],
    }
    monkeypatch.setattr("scrape._fetch_page",
                        lambda q: _paged_response(pages[q["start"]], 18))
    out = fetch_all()
    vins = [r["vin"] for r in out["result"]["pagedVehicles"]["records"]]
    assert len(vins) == len(set(vins))
    assert vins.count(shared) == 1
    assert len(vins) == (PAGE_SIZE - 1) + 1 + 6


def test_fetch_all_logs_coverage_shortfall_without_aborting(monkeypatch, tmp_path):
    """Collecting fewer VINs than the API's own totalCount is the silent
    failure mode that hid the missing page — log it, but keep the run alive."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    import json as _json
    import scrape
    log = tmp_path / "anomalies.jsonl"
    monkeypatch.setattr(scrape, "ANOMALIES_LOG", log)

    pages = {"0": [f"V{i}" for i in range(scrape.PAGE_SIZE)], "1": [f"W{i}" for i in range(3)]}
    monkeypatch.setattr("scrape._fetch_page",
                        lambda q: _paged_response(pages[q["start"]], 40))

    out = fetch_all()  # does not raise
    assert len(out["result"]["pagedVehicles"]["records"]) == scrape.PAGE_SIZE + 3
    entry = _json.loads(log.read_text().splitlines()[0])
    assert entry["kind"] == "coverage_shortfall"
    assert entry["collected"] == scrape.PAGE_SIZE + 3
    assert entry["reported_total"] == 40


def test_fetch_all_aborts_below_expected_min_pool(monkeypatch):
    """If the walk produces fewer than EXPECTED_MIN_POOL records, raise.

    This is the tripwire that fired for ~16h on 2026-08-18/19 when count=24
    began returning 0 records. Per CODE_REVIEW.md TODO 1.
    """
    from scrape import EXPECTED_MIN_POOL
    monkeypatch.delenv("DRY_RUN", raising=False)

    # Page 0 comes back short with fewer records than the floor.
    response = _paged_response([f"V{i:017d}" for i in range(10)], 53)
    monkeypatch.setattr("scrape._fetch_page", lambda q: response)

    with pytest.raises(RuntimeError, match=f"below expected minimum {EXPECTED_MIN_POOL}"):
        fetch_all()


def test_fetch_all_aborts_when_pages_never_end(monkeypatch):
    """A pagination contract change that yields full pages forever must abort
    rather than loop — MAX_PAGES is the runaway guard."""
    from scrape import MAX_PAGES, PAGE_SIZE
    monkeypatch.delenv("DRY_RUN", raising=False)

    counter = {"n": 0}

    def mock_fetch(query):
        counter["n"] += 1
        base = counter["n"] * 1000
        return _paged_response([f"V{base + i}" for i in range(PAGE_SIZE)], 999)

    monkeypatch.setattr("scrape._fetch_page", mock_fetch)
    with pytest.raises(RuntimeError, match=f"walked all {MAX_PAGES} pages"):
        fetch_all()
    assert counter["n"] == MAX_PAGES


def test_save_snapshot_filename_format(tmp_path, payload):
    when = datetime(2026, 4, 26, 12, 30, 45, tzinfo=timezone.utc)
    out = save_snapshot(payload, when=when, out_dir=tmp_path)
    assert out.name == "20260426_123045.json.gz"
    assert out.exists()


def test_save_snapshot_round_trip(tmp_path, payload):
    out = save_snapshot(payload, out_dir=tmp_path)
    with gzip.open(out, "rt", encoding="utf-8") as f:
        recovered = json.load(f)
    assert recovered == payload


def test_save_snapshot_creates_directory(tmp_path, payload):
    nested = tmp_path / "deep" / "nested" / "dir"
    out = save_snapshot(payload, out_dir=nested)
    assert nested.is_dir()
    assert out.parent == nested


def test_parsed_record_is_serializable(raw_records):
    """asdict() must round-trip through JSON for digest/CLI output."""
    p = parse_record(raw_records[0])
    from dataclasses import asdict
    d = asdict(p)
    json.dumps(d)  # must not raise
    assert d["vin"] == p.vin
