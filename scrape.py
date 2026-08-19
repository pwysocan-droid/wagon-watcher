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

# Quarantine floor for implausible prices. The API returned msrp=0 for 10
# records on the 2026-04-26 21:59 poll; those rows reached price_history and
# skewed the 2026-07-30 EOM analysis (analysis/eom_pattern.md) before being
# deleted. CPO wagons are never ≤ $1,000, so anything at or below the floor
# is treated as missing and logged to data/anomalies.jsonl for visibility.
PRICE_ANOMALY_FLOOR = 1_000
ANOMALIES_LOG = ROOT / "data" / "anomalies.jsonl"

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
    "start": "0",  # page index, not an offset — see "Pagination" below
    "withFilters": "true",
    "zip": "90210",
}

# Pagination — re-verified live 2026-08-19, after the watcher aborted on
# every poll for ~16 hours.
#
# `start` is a ZERO-BASED PAGE INDEX and `count` is the page size. Page p
# returns records [p*count, (p+1)*count). The original recon read the same
# behavior as "start is a misnomer, vary count instead", which fit the
# observations but had the semantics backwards:
#
#   start=0&count=12 → the 12 NEAREST cars (page 0)
#   start=1&count=12 → the next 11         (page 1; short page = the end)
#   start=2&count=12 → 0 records           (past the end)
#
# Consequences of the old COUNTS_FOR_UNION strategy (two calls, both
# start=1, count=12 then count=24 — i.e. pages 1 and 1-of-size-24, records
# 12..47):
#   - It never fetched page 0, so the nearest listings were invisible for
#     the life of the project. On 2026-08-19 page 0 held two CA cars 71.8
#     miles away — the closest in the feed and the most relevant to a
#     Los Angeles buyer — neither of which had ever entered the DB.
#   - It broke outright when the pool fell to 23: count=24 returns 0
#     records at that size, leaving an 11-VIN union that tripped
#     EXPECTED_MIN_POOL and aborted every run.
#
# Walk pages until a short page (fewer than PAGE_SIZE records) arrives —
# that is how the API signals the end. MAX_PAGES is a runaway guard.
PAGE_SIZE = 12
MAX_PAGES = 25


# Coarse "endpoint returned almost nothing" tripwire. This is a backstop, not
# the primary defense: reconcile.py's relative check (abort if found < 0.5 *
# last successful count) is what catches a real collapse, and it self-adjusts
# as inventory shifts. This floor only matters when there's no last_count to
# compare against (e.g. first run on an empty DB). 12 == one count=12 window,
# so anything below it means even a single call came back broken.
#
# Originally 25, set at recon when the national E450S4+WGN pool was ≥34. It
# was lowered to 12 on 2026-05-21 because it kept tripping on "healthy" data
# — which, in hindsight, was the pagination bug above quietly serving a
# truncated pool (records 12..47 of it), not a thinning market. With page 0
# restored the real pool reads 23 as of 2026-08-19.
EXPECTED_MIN_POOL = 12


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


def _log_anomaly(kind: str, **fields: Any) -> None:
    """Append one record to data/anomalies.jsonl.

    Best-effort: a logging failure must never fail the scrape itself."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **fields,
    }
    try:
        ANOMALIES_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ANOMALIES_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _log_price_anomaly(vin: str, raw_msrp: int) -> None:
    _log_anomaly(
        "price_quarantined",
        vin=vin,
        raw_msrp=raw_msrp,
        reason=f"msrp <= {PRICE_ANOMALY_FLOOR}",
    )


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

    # Quarantine implausible prices (see PRICE_ANOMALY_FLOOR): treat as
    # missing so downstream code skips pricing operations until the API
    # recovers on a later poll, and log so a recurrence is visible.
    raw_msrp = _to_int(record.get("msrp"))
    if raw_msrp is not None and raw_msrp <= PRICE_ANOMALY_FLOOR:
        _log_price_anomaly(record["vin"], raw_msrp)
        mbusa_price = None
    else:
        mbusa_price = raw_msrp

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
    """Fetch the full filtered pool by walking the API's pages.

    Live mode: requests page 0, 1, 2, … at PAGE_SIZE records per page until a
    short page signals the end (see "Pagination" above), unions by VIN, and
    returns a synthetic single-payload response with the union as `records`
    and a corrected `paging` block.

    DRY_RUN=1 (env or arg) reads fixtures/sample_response.json instead.
    """
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN") == "1"
    if dry_run:
        return json.loads(FIXTURE.read_text())

    base_query = {**(query or DEFAULT_QUERY)}

    by_vin: dict[str, dict] = {}
    base_response: dict | None = None
    reported_total: int | None = None
    pages_walked = 0

    for page in range(MAX_PAGES):
        response = _fetch_page(
            {**base_query, "start": str(page), "count": str(PAGE_SIZE)}
        )
        if base_response is None:
            base_response = response
        paged = response["result"]["pagedVehicles"]
        page_records = paged.get("records") or []
        if reported_total is None:
            reported_total = (paged.get("paging") or {}).get("totalCount")
        for r in page_records:
            by_vin[r["vin"]] = r
        pages_walked += 1
        if len(page_records) < PAGE_SIZE:
            break  # short (or empty) page — that's the end of the pool
    else:
        raise RuntimeError(
            f"fetch_all walked all {MAX_PAGES} pages without reaching a "
            f"short page (collected {len(by_vin)} VINs). The pagination "
            f"contract may have changed again — verify before trusting the "
            f"data. Aborting before reconcile."
        )

    assert base_response is not None  # MAX_PAGES >= 1
    records = list(by_vin.values())

    if len(records) < EXPECTED_MIN_POOL:
        raise RuntimeError(
            f"fetch_all returned {len(records)} records from {pages_walked} "
            f"page(s), below expected minimum {EXPECTED_MIN_POOL}. Verify the "
            f"pagination contract still holds (start = zero-based page index, "
            f"count = page size). Aborting before reconcile."
        )

    # Coverage tripwire. The union should match the API's own totalCount;
    # a shortfall means whole pages are going missing — precisely the silent
    # failure the old union strategy hid for months. Log it instead of
    # aborting: totalCount has been unreliable before, and a stale count
    # shouldn't take the watcher offline when the data itself looks sane.
    if reported_total is not None and len(records) < reported_total:
        _log_anomaly(
            "coverage_shortfall",
            collected=len(records),
            reported_total=reported_total,
            pages_walked=pages_walked,
            reason="union smaller than the API's totalCount",
        )
        print(
            f"WARNING: collected {len(records)} of {reported_total} reported "
            f"records across {pages_walked} page(s) — possible missed page",
            file=sys.stderr,
        )

    base_response["result"]["pagedVehicles"]["records"] = records
    base_response["result"]["pagedVehicles"]["paging"] = {
        "totalCount": len(records),  # corrected — count what we actually got
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
