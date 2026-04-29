"""Orchestrator: fetch → save snapshot → parse → reconcile → emit latest.json.

Single entry point for the GitHub Actions workflow. Notifications are
deliberately not imported here — step 5 will wire that in.

Exit codes:
    0  reconcile completed (status='ok')
    1  reconcile aborted (health check tripped); the workflow should
       commit the runs row + latest.json and then surface the failure.

Side effects (always, in order):
    1. raw_snapshots/<UTC timestamp>.json.gz — every run, even on abort
    2. data/inventory.db — schema migrated, listings/price_history/runs updated
       (on abort: only the runs row is written)
    3. data/latest.json — current active+reappeared inventory, pretty-printed
    4. .run-commit-msg.txt — a one-line summary; the workflow uses this as
       the commit message for the auto-commit
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import notify
from db import DB_PATH, connect, migrate
from reconcile import (
    _matching_watchlist_labels,
    mbusa_listing_url,
    reconcile,
)
from scrape import RAW_SNAPSHOTS, ParsedRecord, fetch_all, parse_response, save_snapshot

ROOT = Path(__file__).parent
LATEST_JSON = ROOT / "data" / "latest.json"
PRICE_HISTORY_JSON = ROOT / "data" / "price_history.json"
COMMIT_MSG_FILE = ROOT / ".run-commit-msg.txt"

# How far back to keep 'gone' VINs in the price-history export. Active and
# reappeared VINs are always included regardless of last_seen.
PRICE_HISTORY_GONE_RETENTION = timedelta(days=30)
PRICE_HISTORY_SCHEMA_VERSION = 1

def _row_to_parsed_record(row) -> ParsedRecord:
    """Adapter: a listings-table row → a ParsedRecord-shaped object so
    reconcile._matching_watchlist_labels can be reused for the dashboard's
    'Within criteria' KPI without duplicating spec evaluation."""
    return ParsedRecord(
        vin=row["vin"],
        year=row["year"],
        model=row["model"],
        trim=row["trim"],
        body_style=row["body_style"],
        mbusa_price=row["current_price"],
        mileage=row["mileage_first_seen"],
        exterior_color=row["exterior_color"],
        exterior_color_code=None,
        interior_color=row["interior_color"],
        engine=None,
        is_certified=None,
        dealer_id=None,
        dealer_name=row["dealer_name"],
        dealer_zip=row["dealer_zip"],
        dealer_state=row["dealer_state"],
        dealer_distance_miles=row["distance_miles"],
        dealer_site_url=row["dealer_site_url"],
        photo_url=row["photo_url"],
        stock_id=None,
        options_json=None,
    )


def _days_on_lot(first_seen, now: datetime) -> int:
    if first_seen is None:
        return 0
    if isinstance(first_seen, str):
        first_seen = datetime.fromisoformat(first_seen)
    if first_seen.tzinfo is None:
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    return max(0, (now - first_seen).days)


def write_latest_json(conn, out_path: Path) -> Path:
    """Dump the dashboard-shaped payload: active+reappeared listings with
    derived fields (current_price, days_on_lot, is_watchlist_match,
    tier1_count, mbusa_listing_url) plus a `kpis` block. The Next.js
    dashboard reads this file via raw GitHub URL and renders directly —
    no rebuild needed when the watcher commits new data."""
    now = datetime.now(timezone.utc)

    rows = conn.execute(
        "SELECT l.vin, l.year, l.model, l.trim, l.body_style, "
        "       l.exterior_color, l.interior_color, "
        "       l.dealer_name, l.dealer_state, l.dealer_zip, "
        "       l.distance_miles, l.mileage_first_seen, l.photo_url, "
        "       l.listing_url, l.status, l.first_seen, l.last_seen, "
        "       l.fair_price_pct, l.fair_price_tier, "
        "       l.dealer_site_price, l.dealer_site_url, "
        "       (SELECT price FROM price_history "
        "        WHERE vin = l.vin AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS current_price, "
        "       (SELECT COUNT(*) FROM notifications "
        "        WHERE vin = l.vin AND tier = 1 AND success = 1) AS tier1_count "
        "FROM listings l "
        "WHERE l.status IN ('active', 'reappeared') "
        "ORDER BY l.distance_miles ASC NULLS LAST, l.last_seen DESC"
    ).fetchall()

    listings = []
    within_criteria_count = 0
    prices: list[int] = []
    for row in rows:
        d = dict(row)
        # Watchlist match: re-evaluate active specs against the current state.
        # Reuse reconcile's matcher via a ParsedRecord-shaped adapter.
        labels = _matching_watchlist_labels(conn, _row_to_parsed_record(row))
        d["is_watchlist_match"] = bool(labels)
        d["watchlist_labels"] = labels
        if labels:
            within_criteria_count += 1
        d["days_on_lot"] = _days_on_lot(row["first_seen"], now)
        d["mbusa_listing_url"] = mbusa_listing_url(row["vin"])
        if row["current_price"] is not None and row["current_price"] > 0:
            prices.append(row["current_price"])
        listings.append(d)

    median_asking = (
        int(median(prices)) if prices else None
    )

    week_ago = (now - timedelta(days=7)).isoformat()
    tier1_recent = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications "
        "WHERE tier = 1 AND success = 1 AND sent_at >= ?",
        (week_ago,),
    ).fetchone()["c"]

    payload = {
        "generated_at": now.isoformat(),
        "count": len(listings),
        "kpis": {
            "national_pool": len(listings),
            "within_criteria": within_criteria_count,
            "median_asking": median_asking,
            "tier1_alerts_7d": tier1_recent,
        },
        "listings": listings,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return out_path


def write_price_history_json(conn, out_path: Path) -> Path:
    """Export per-VIN price-history series to data/price_history.json.

    Per HANDOFF_price_history_export.md: VIN-keyed for O(1) client lookups,
    one observation per distinct price/mileage row in price_history (already
    deduped by reconcile), server-computed stats so the browser doesn't
    redo the math per chart. Gone VINs are kept for 30 days post-vanish,
    then dropped — file size estimate ≈80 KB at current volume.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - PRICE_HISTORY_GONE_RETENTION).isoformat()

    listings = conn.execute(
        "SELECT vin, year, trim, dealer_name, first_seen, last_seen, "
        "       mileage_first_seen, status "
        "FROM listings "
        "WHERE status IN ('active', 'reappeared') "
        "   OR last_seen >= ?",
        (cutoff,),
    ).fetchall()

    payload = {
        "generated_at": now.isoformat(),
        "schema_version": PRICE_HISTORY_SCHEMA_VERSION,
        "vins": {},
    }

    for row in listings:
        vin = row["vin"]
        observations = conn.execute(
            "SELECT observed_at, price, mileage FROM price_history "
            "WHERE vin = ? AND price > 0 "
            "ORDER BY observed_at ASC, id ASC",
            (vin,),
        ).fetchall()

        if not observations:
            continue  # skip VINs without any usable price data

        prices = [o["price"] for o in observations]
        first_price = prices[0]
        current_price = prices[-1]
        current_mileage = observations[-1]["mileage"]

        total_drop_pct = (
            round((current_price - first_price) / first_price * 100, 2)
            if first_price > 0 else 0.0
        )

        first_seen = row["first_seen"]
        if isinstance(first_seen, str):
            first_seen_dt = datetime.fromisoformat(first_seen)
        else:
            first_seen_dt = first_seen
        if first_seen_dt.tzinfo is None:
            first_seen_dt = first_seen_dt.replace(tzinfo=timezone.utc)
        days_observed = max(0, (now - first_seen_dt).days)

        payload["vins"][vin] = {
            "year": row["year"],
            "trim": row["trim"],
            "dealer": row["dealer_name"],
            "first_seen_at": first_seen if isinstance(first_seen, str) else first_seen.isoformat(),
            "current_price": current_price,
            "current_mileage": current_mileage,
            "status": row["status"],
            "observations": [
                {
                    "observed_at": o["observed_at"],
                    "price": o["price"],
                    "mileage": o["mileage"],
                }
                for o in observations
            ],
            "stats": {
                "all_time_low": min(prices),
                "all_time_high": max(prices),
                "total_drop_pct": total_drop_pct,
                "n_observations": len(observations),
                "days_observed": days_observed,
            },
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return out_path


def commit_message(result: dict, when: datetime) -> str:
    ts = when.strftime("%Y-%m-%dT%H:%MZ")
    s = result["stats"]
    if result["status"] == "aborted":
        reason = (result.get("aborted_reason") or "unknown").replace("\n", " ")
        return f"data: {ts} [ABORTED — {reason}]"
    return (
        f"data: {ts} "
        f"[{s['listings_found']} listings | "
        f"new={s['new_count']} changed={s['changed_count']} "
        f"gone={s['gone_count']} reappeared={s['reappeared_count']}]"
    )


def main(
    *,
    db_path: Path = DB_PATH,
    snapshots_dir: Path = RAW_SNAPSHOTS,
    latest_json: Path = LATEST_JSON,
    price_history_json: Path = PRICE_HISTORY_JSON,
    commit_msg_file: Path = COMMIT_MSG_FILE,
) -> int:
    started_at = datetime.now(timezone.utc)
    payload = fetch_all()
    save_snapshot(payload, when=started_at, out_dir=snapshots_dir)

    parsed, _paging = parse_response(payload)

    conn = connect(db_path)
    try:
        migrate(conn)
        result = reconcile(parsed, conn, now=started_at)
        write_latest_json(conn, latest_json)
        write_price_history_json(conn, price_history_json)

        # Tier 1: scraper_aborted (the fourth Tier 1 case — the other three
        # fire from inside reconcile.py). Priority-2 with retry/expire so the
        # alert re-fires every 30 seconds for up to an hour until acked.
        if result["status"] == "aborted":
            reason = result.get("aborted_reason") or "unknown"
            details = {
                "Tripped at": started_at.isoformat(timespec="seconds"),
                "Reason": reason,
                "Effect": "No listings were modified. The runs row was logged.",
            }
            notify.send(
                tier=1, event_type="scraper_aborted",
                title="WAGON-WATCHER ABORTED",
                body="\n".join(f"{k}: {v}" for k, v in details.items()),
                year_trim="health-check failure",
                details=details,
                conn=conn,
            )
            conn.commit()
    finally:
        conn.close()

    msg = commit_message(result, started_at)
    commit_msg_file.write_text(msg + "\n")
    print(msg)

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
