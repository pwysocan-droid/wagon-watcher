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

# Probed 2026-04-28: MBUSA's portal serves a Next-style SPA at this path.
# The HTML body is JS-rendered (returns 200 for any VIN string) but the URL
# is a valid clickable target — opens the right listing in a browser when
# the VIN is in current inventory. Honors PROJECT.md's "VIN as canonical
# link" rule across notifications, the alert log, and the weekly digest.
MBUSA_LISTING_URL_TEMPLATE = "https://www.mbusa.com/en/cpo/inventory/details/{vin}"


def mbusa_listing_url(vin: str) -> str:
    return MBUSA_LISTING_URL_TEMPLATE.format(vin=vin)

DEFAULT_QUERY: dict[str, str] = {
    "distance": "ANY",
    "invType": "cpo",
    "class": "E",
    "model": "E450S4",
    "bodyStyleId": "WGN",
    "resvOnly": "false",
    "sortBy": "distance-asc",
    "start": "1",
    "withFilters": "true",
    "zip": "90210",
}

# Per recon 2026-04-26: the API does NOT support offset-style pagination via
# `start`. Different `start` values return disjoint windows; `start>=12`
# returns 0 records. The `count` parameter, however, is not capped at 12 as
# original recon claimed — `count=24` works. count=12 and count=24 (both with
# start=1) return DISJOINT sets of records that, when unioned, cover the full
# filtered pool. Three consecutive runs returned the same 36 VINs with
# consistent prices, so this strategy is deterministic.
COUNTS_FOR_UNION: tuple[str, ...] = ("12", "24")

# Defensive floor for the union strategy. The E450S4+WGN national pool has
# been ≥34 since recon. Below this, the most likely explanation is that
# MBUSA has changed the backend so count=12 and count=24 now return
# overlapping records — we'd silently lose half the dataset. Failing loud
# inside the scraper is cheaper than letting the reconciler's 50% health
# check catch it after one bad run is already logged.
EXPECTED_MIN_POOL = 25


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

    # Defensive: the API has been observed returning msrp=0 transiently
    # (10 records on the 2026-04-26 21:59 poll). CPO wagons are never $0,
    # so treat 0/negative as missing and let downstream code skip pricing
    # operations until the API recovers on a later poll.
    raw_msrp = _to_int(record.get("msrp"))
    mbusa_price = raw_msrp if (raw_msrp is not None and raw_msrp > 0) else None

    return ParsedRecord(
        vin=record["vin"],
        year=_to_int(record.get("year")),
        model=record.get("modelName"),
        trim=record.get("modelId"),
        body_style=record.get("bodyStyleId"),
        mbusa_price=mbusa_price,
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


def _fetch_page(query: dict[str, str]) -> dict:
    """Hit the live endpoint with the given full query. Real HTTP."""
    url = ENDPOINT + "?" + urlencode(query)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 — known endpoint
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} from {url}")
        return json.loads(resp.read().decode("utf-8"))


def fetch_all(
    query: dict[str, str] | None = None,
    dry_run: bool | None = None,
) -> dict:
    """Fetch the full filtered pool by unioning two API calls.

    Live mode: makes len(COUNTS_FOR_UNION) calls (count=12, count=24), unions
    by VIN, and returns a synthetic single-payload response with the union as
    `records` and a corrected `paging` block (the API's own totalCount lies).

    DRY_RUN=1 (env or arg) reads fixtures/sample_response.json instead.
    """
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN") == "1"
    if dry_run:
        return json.loads(FIXTURE.read_text())

    base_query = {**(query or DEFAULT_QUERY)}

    by_vin: dict[str, dict] = {}
    base_response: dict | None = None
    for count in COUNTS_FOR_UNION:
        response = _fetch_page({**base_query, "count": count})
        if base_response is None:
            base_response = response
        for r in response["result"]["pagedVehicles"]["records"]:
            by_vin[r["vin"]] = r

    assert base_response is not None  # COUNTS_FOR_UNION is non-empty
    records = list(by_vin.values())

    if len(records) < EXPECTED_MIN_POOL:
        raise RuntimeError(
            f"fetch_all returned {len(records)} records, below expected "
            f"minimum {EXPECTED_MIN_POOL}. The two calls "
            f"(count={', count='.join(COUNTS_FOR_UNION)}) may now return "
            f"overlapping records — verify the union strategy is still "
            f"disjoint. Aborting before reconcile."
        )

    base_response["result"]["pagedVehicles"]["records"] = records
    base_response["result"]["pagedVehicles"]["paging"] = {
        "totalCount": len(records),  # corrected — API's totalCount is unreliable
        "currentOffset": 0,
        "currentCount": len(records),
    }
    return base_response


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
