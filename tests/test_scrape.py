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


def test_fetch_all_live_unions_two_count_responses(monkeypatch):
    """Live mode makes two calls (count=12, count=24) and unions by VIN.

    The MBUSA API doesn't paginate offset-style; this is the workaround
    documented in fixtures/endpoint_notes.md (recon 2026-04-26).
    """
    monkeypatch.delenv("DRY_RUN", raising=False)

    def make_response(vins: list[str]) -> dict:
        return {
            "result": {"pagedVehicles": {
                "records": [{"vin": v} for v in vins],
                "paging": {"totalCount": 53, "currentOffset": 0,
                           "currentCount": len(vins)},
            }, "facets": {}},
            "status": {"code": 200, "ok": True, "tmstmp": "0", "traceId": "x"},
            "messages": [],
            "success": True,
        }

    # The two calls return disjoint VIN sets (mirrors observed API behavior).
    response_for_count = {
        "12": make_response([f"VIN_A_{i}" for i in range(12)]),
        "24": make_response([f"VIN_B_{i}" for i in range(24)]),
    }
    calls: list[str] = []

    def mock_fetch(query):
        count = query["count"]
        calls.append(count)
        return response_for_count[count]

    monkeypatch.setattr("scrape._fetch_page", mock_fetch)

    out = fetch_all()
    assert calls == ["12", "24"]

    records = out["result"]["pagedVehicles"]["records"]
    vins = {r["vin"] for r in records}
    assert vins == ({f"VIN_A_{i}" for i in range(12)}
                    | {f"VIN_B_{i}" for i in range(24)})
    assert len(records) == 36

    paging = out["result"]["pagedVehicles"]["paging"]
    assert paging["totalCount"] == 36          # corrected from API's lying 53
    assert paging["currentCount"] == 36


def test_fetch_all_live_dedupes_overlapping_vins(monkeypatch):
    """If the two calls share a VIN, it appears once in the union."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    shared = "SHARED_VIN_0000001"

    def make_response(vins):
        return {
            "result": {"pagedVehicles": {
                "records": [{"vin": v} for v in vins],
                "paging": {"totalCount": 99, "currentOffset": 0,
                           "currentCount": len(vins)},
            }, "facets": {}},
            "status": {"code": 200},
            "success": True,
        }

    # Total ≥ EXPECTED_MIN_POOL so the sanity check passes.
    responses = iter([
        make_response([shared] + [f"A{i}" for i in range(13)]),
        make_response([shared] + [f"B{i}" for i in range(15)]),
    ])
    monkeypatch.setattr("scrape._fetch_page", lambda q: next(responses))

    out = fetch_all()
    vins = {r["vin"] for r in out["result"]["pagedVehicles"]["records"]}
    expected = {shared} | {f"A{i}" for i in range(13)} | {f"B{i}" for i in range(15)}
    assert vins == expected
    assert len(vins) == 29  # not 30 — shared appears once


def test_fetch_all_aborts_below_expected_min_pool(monkeypatch):
    """If the union produces fewer than EXPECTED_MIN_POOL records, raise.

    Defends against the silent failure where MBUSA changes the backend so
    count=12 and count=24 return overlapping records — we'd quietly lose
    half the dataset. Per CODE_REVIEW.md TODO 1.
    """
    from scrape import EXPECTED_MIN_POOL
    monkeypatch.delenv("DRY_RUN", raising=False)

    # Both calls return the SAME 12 records — total union = 12, < 25.
    same_vins = [{"vin": f"V{i:017d}"} for i in range(12)]
    response = {
        "result": {"pagedVehicles": {
            "records": same_vins,
            "paging": {"totalCount": 53, "currentOffset": 0, "currentCount": 12},
        }, "facets": {}},
        "status": {"code": 200},
        "success": True,
    }
    monkeypatch.setattr("scrape._fetch_page", lambda q: response)

    with pytest.raises(RuntimeError, match=f"below expected minimum {EXPECTED_MIN_POOL}"):
        fetch_all()


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
