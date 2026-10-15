"""One-off probe: is the MBUSA API hiding in-scope inventory?

Trigger: a 2025 E450 All-Terrain at MB West Covina ($73,763, ~25 mi from
90210) shows on iSeeCars but never in our pool; and three cars outside the
feed (Youngstown OH, Georgetown TX, Valley Imports ND) describe themselves as
Mercedes-Benz certified on Cars.com. Either they aren't CPO in MBUSA's system
(fine) or the query is missing them (serious).

Each probe varies one thing against the production query (scrape.DEFAULT_QUERY):
  - nationwide baseline, all pages — does the union match totalCount?
  - local radius around each target dealer's ZIP — a small result set can't
    be capped, so absence there means absence from the feed
  - model filter dropped (class E + wagon only) — wrong drivetrain code?
  - body-style filter dropped — mis-tagged body style?
  - invType=used — present as plain used (not certified) inventory?

Usage: python3 analysis/api_cap_probe.py   (live HTTP, ~30 requests)
Findings: analysis/api_cap_probe.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scrape  # noqa: E402

TARGETS = {
    # vin (or None when unknown) -> (label, dealer-name fragment, dealer ZIP)
    "west_covina": (None, "West Covina", "91790"),
    "youngstown": ("W1KLH6FB5SA129436", "Youngstown", "44515"),
    "georgetown": ("W1KLH6FB8SA133447", "Georgetown", "78626"),
    "valley_imports": ("W1KLH6FB2SA084620", "Valley", "58103"),
    "rochester_mn": (None, "Rochester", "55901"),
}


def walk(query: dict[str, str]) -> tuple[list[dict], int | None]:
    """All pages of a query (same contract as scrape.fetch_all, no tripwires)."""
    out: dict[str, dict] = {}
    total = None
    for page in range(scrape.MAX_PAGES):
        resp = scrape._fetch_page({**query, "start": str(page), "count": str(scrape.PAGE_SIZE)})
        paged = resp["result"]["pagedVehicles"]
        recs = paged.get("records") or []
        if total is None:
            total = (paged.get("paging") or {}).get("totalCount")
        for r in recs:
            out[r["vin"]] = r
        time.sleep(0.5)
        if len(recs) < scrape.PAGE_SIZE:
            break
    return list(out.values()), total


def describe(r: dict) -> str:
    p = scrape.parse_record(r)
    return (f"{p.vin} {p.year} {p.model or ''} {p.trim or ''} {p.body_style or ''} "
            f"{p.mileage or '?'}mi ${p.mbusa_price or '?'} · {p.dealer_name}, {p.dealer_state}")


def hits(records: list[dict], vin: str | None, dealer_frag: str) -> list[str]:
    found = []
    for r in records:
        p = scrape.parse_record(r)
        if (vin and p.vin == vin) or (dealer_frag.lower() in (p.dealer_name or "").lower()):
            found.append(describe(r))
    return found


def main() -> int:
    base = dict(scrape.DEFAULT_QUERY)

    print("## 1. Production query, nationwide")
    recs, total = walk(base)
    print(f"union={len(recs)} totalCount={total}")
    for key, (vin, frag, _) in TARGETS.items():
        print(f"  {key}: {hits(recs, vin, frag) or 'absent'}")

    variants = {
        "production filters": base,
        "no model filter (class E, WGN)": {k: v for k, v in base.items() if k != "model"},
        "no body-style filter (E450S4)": {k: v for k, v in base.items() if k != "bodyStyleId"},
        "invType=used": {**base, "invType": "used"},
    }
    print("\n## 2. Local radius (100 mi) around each target dealer")
    for key, (vin, frag, zip_) in TARGETS.items():
        print(f"\n### {key} (zip {zip_})")
        for label, q in variants.items():
            try:
                recs, total = walk({**q, "zip": zip_, "distance": "100"})
            except Exception as e:  # noqa: BLE001 — probe; report and continue
                print(f"  {label}: ERROR {e}")
                continue
            h = hits(recs, vin, frag)
            print(f"  {label}: n={len(recs)} total={total} -> {h or 'target absent'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
