"""Fetch and parse MBUSA CPO inventory.

Pure with respect to the DB — never imports db.py, never writes to SQLite.
Saves the raw API response to raw_snapshots/ on every run.

Honors DRY_RUN=1: reads fixtures/sample_response.json instead of hitting the
live endpoint. Used by step 2 tests and local replay.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
FIXTURE = ROOT / "fixtures" / "sample_response.json"
RAW_SNAPSHOTS = ROOT / "raw_snapshots"

ENDPOINT = "https://nafta-service.mbusa.com/api/inv/v1/en_us/used/vehicles/search"
USER_AGENT = "mb-wagon-watcher/1.0 (personal research; pwysocan@gmail.com)"
PAGE_SIZE = 12

DEFAULT_QUERY: dict[str, str] = {
    "count": "12",
    "distance": "ANY",
    "invType": "cpo",
    "class": "E",
    "model": "E450S4",
    "bodyStyleId": "WGN",
    "resvOnly": "false",
    "sortBy": "distance-asc",
    "withFilters": "true",
    "zip": "90210",
}


@dataclass
class ParsedRecord:
    vin: str
    year: int | None
    model: str | None
    trim: str | None
    body_style: str | None
    mbusa_price: int | None
    mileage: int | None
    exterior_color: str | None
    exterior_color_code: str | None
    interior_color: str | None
    engine: str | None
    is_certified: bool | None
    dealer_id: str | None
    dealer_name: str | None
    dealer_zip: str | None
    dealer_state: str | None
    dealer_distance_miles: float | None
    dealer_site_url: str | None
    photo_url: str | None
    stock_id: str | None
    options_json: str | None


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first(seq: Any) -> Any:
    if isinstance(seq, list) and seq:
        return seq[0]
    return None


def parse_record(record: dict) -> ParsedRecord:
    """Map one raw API record to the watcher's domain model.

    Per fixtures/endpoint_notes.md: live data lives under
    record.usedVehicleAttributes — record root is unreliable past record #1.
    """
    uva = record.get("usedVehicleAttributes") or {}
    dealer = uva.get("dealer") or {}
    dealer_addr = _first(dealer.get("address")) or {}
    if not isinstance(dealer_addr, dict):
        dealer_addr = {}
    dealer_loc = dealer_addr.get("location") or {}
    paint = record.get("paint") or {}
    upholstery = record.get("upholstery") or {}
    images = uva.get("images") or []
    option_list = uva.get("optionList") or []

    return ParsedRecord(
        vin=record["vin"],
        year=_to_int(record.get("year")),
        model=record.get("modelName"),
        trim=record.get("modelId"),
        body_style=record.get("bodyStyleId"),
        mbusa_price=_to_int(record.get("msrp")),
        mileage=_to_int(uva.get("mileage")),
        exterior_color=paint.get("name"),
        exterior_color_code=record.get("exteriorMetaColor"),
        interior_color=upholstery.get("name"),
        engine=record.get("engine"),
        is_certified=uva.get("certified"),
        dealer_id=record.get("dealerId"),
        dealer_name=dealer.get("name"),
        dealer_zip=dealer_addr.get("zip"),
        dealer_state=dealer_addr.get("state"),
        dealer_distance_miles=_to_float(dealer_loc.get("dist")),
        dealer_site_url=dealer.get("url"),
        photo_url=images[0] if images else None,
        stock_id=record.get("stockId"),
        options_json=json.dumps(option_list) if option_list else None,
    )


def parse_response(payload: dict) -> tuple[list[ParsedRecord], dict]:
    """Parse a full API response. Returns (records, paging meta).

    Raises if `success` is false or `status.code` is not 200 — callers
    should treat this as an abort signal (per the health-check rule).
    """
    if not payload.get("success"):
        raise ValueError(f"API reported success=false: {payload.get('messages')}")
    status = payload.get("status") or {}
    if status.get("code") != 200:
        raise ValueError(f"API status code is {status.get('code')}, not 200")

    paged = payload["result"]["pagedVehicles"]
    return [parse_record(r) for r in paged["records"]], paged["paging"]


def _fetch_page(start: int, query: dict[str, str]) -> dict:
    """Hit the live endpoint for one page. Real HTTP — only outside DRY_RUN."""
    params = {**query, "start": str(start)}
    url = ENDPOINT + "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 — known endpoint
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} from {url}")
        return json.loads(resp.read().decode("utf-8"))


def fetch_all(
    query: dict[str, str] | None = None,
    dry_run: bool | None = None,
) -> dict:
    """Walk all pages and return a single merged response payload.

    DRY_RUN=1 (env or explicit arg) reads fixtures/sample_response.json.
    """
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN") == "1"
    if dry_run:
        return json.loads(FIXTURE.read_text())

    if query is None:
        query = DEFAULT_QUERY

    first = _fetch_page(1, query)
    paging = first["result"]["pagedVehicles"]["paging"]
    total = paging.get("totalCount", 0)

    records: list[dict] = list(first["result"]["pagedVehicles"]["records"])
    next_start = 1 + len(records)

    while len(records) < total:
        page = _fetch_page(next_start, query)
        page_records = page["result"]["pagedVehicles"]["records"]
        if not page_records:
            break
        records.extend(page_records)
        next_start += len(page_records)

    merged = first
    merged["result"]["pagedVehicles"]["records"] = records
    merged["result"]["pagedVehicles"]["paging"] = {
        "totalCount": total,
        "currentOffset": 0,
        "currentCount": len(records),
    }
    return merged


def save_snapshot(
    payload: dict,
    when: datetime | None = None,
    out_dir: Path = RAW_SNAPSHOTS,
) -> Path:
    """Write the raw response to <out_dir>/YYYYMMDD_HHMMSS.json.gz (UTC)."""
    when = when or datetime.now(timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = when.strftime("%Y%m%d_%H%M%S") + ".json.gz"
    out = out_dir / name
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    return out


def main(argv: list[str]) -> int:
    payload = fetch_all()
    snap = save_snapshot(payload)
    parsed, paging = parse_response(payload)
    print(f"snapshot: {snap}", file=sys.stderr)
    print(
        f"records:  {len(parsed)} parsed / {paging.get('totalCount')} reported",
        file=sys.stderr,
    )
    json.dump([asdict(p) for p in parsed], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
