"""Diff scrape output against the DB. Writes listings, price_history, runs.

Takes a DB connection (caller controls lifecycle). Honors DRY_RUN by rolling
back the transaction at the end.

Step 5: wires Tier 1 notifications via `notify.send()` for three event types:
  - watchlist_match (new listing matches an active watchlist spec)
  - price_drop_major (existing VIN's price dropped ≥7%)
  - reappeared      (VIN was 'gone', now back)

The fourth Tier 1 case — scraper_aborted — fires from run.py instead.

Per PROJECT.md "Health check": refuses to write if listings_found == 0 OR
listings_found < 0.5 * <last successful run's count>. On abort, writes a
runs row with status='aborted' and emits an 'aborted' event.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import fairprice
import notify
import vin_decode
from scrape import ParsedRecord

PRICE_DROP_TIER1_THRESHOLD = -0.07  # ≥7% drop fires Tier 1
PRICE_DROP_TIER2_THRESHOLD = -0.03  # 3-7% drop fires Tier 2 (Tier 1 takes precedence)


# ---- Listings I/O --------------------------------------------------------

_LISTING_COLUMNS = (
    "vin", "first_seen", "last_seen", "status", "gone_at",
    "dealer_name", "dealer_zip", "dealer_state",
    "year", "model", "trim", "body_style",
    "exterior_color", "interior_color", "mileage_first_seen",
    "photo_url", "listing_url", "options_json", "vin_decode_json",
    "distance_miles",
)


def _insert_listing(conn: sqlite3.Connection, r: ParsedRecord, now: datetime) -> None:
    """Insert a fresh listing. NHTSA decode is best-effort and runs once per
    VIN ever — failures store NULL and the listing tracks normally without."""
    decoded = vin_decode.decode(r.vin)
    decoded_json = json.dumps(decoded) if decoded is not None else None

    conn.execute(
        f"INSERT INTO listings ({', '.join(_LISTING_COLUMNS)}) "
        f"VALUES ({', '.join('?' * len(_LISTING_COLUMNS))})",
        (
            r.vin, now, now, "active", None,
            r.dealer_name, r.dealer_zip, r.dealer_state,
            r.year, r.model, r.trim, r.body_style,
            r.exterior_color, r.interior_color, r.mileage,
            r.photo_url, None,  # listing_url: TODO once MBUSA URL pattern is confirmed
            r.options_json, decoded_json,
            r.dealer_distance_miles,
        ),
    )


def _update_listing(conn: sqlite3.Connection, vin: str, fields: dict[str, Any]) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE listings SET {cols} WHERE vin = ?", (*fields.values(), vin))


# ---- price_history I/O ---------------------------------------------------

def _insert_price_history(
    conn: sqlite3.Connection, vin: str, observed_at: datetime,
    price: int, mileage: int,
) -> None:
    conn.execute(
        "INSERT INTO price_history (vin, observed_at, price, mileage) "
        "VALUES (?, ?, ?, ?)",
        (vin, observed_at, price, mileage),
    )


def _last_price_row(conn: sqlite3.Connection, vin: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT price, mileage FROM price_history "
        "WHERE vin = ? ORDER BY observed_at DESC, id DESC LIMIT 1",
        (vin,),
    ).fetchone()


# ---- runs I/O ------------------------------------------------------------

def _insert_run(
    conn: sqlite3.Connection,
    *,
    started_at: datetime,
    finished_at: datetime,
    listings_found: int,
    new_count: int = 0,
    changed_count: int = 0,
    gone_count: int = 0,
    reappeared_count: int = 0,
    duration_ms: int,
    status: str,
    error_message: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO runs ("
        "started_at, finished_at, listings_found, new_count, changed_count, "
        "gone_count, reappeared_count, duration_ms, status, error_message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (started_at, finished_at, listings_found, new_count, changed_count,
         gone_count, reappeared_count, duration_ms, status, error_message),
    )
    return cur.lastrowid


def _last_successful_count(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT listings_found FROM runs "
        "WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["listings_found"] if row else None


# ---- Watchlist matching --------------------------------------------------

def _matches_spec(record: ParsedRecord, spec: dict) -> bool:
    """AND-within-row evaluation of a watchlist spec against a parsed record.

    Recognized keys: trim, body_style, min_year, max_year, min_mileage,
    max_mileage, min_price, max_price_all_in. Unknown keys are ignored
    (forward-compatible). A None value on the record fails the constraint
    rather than passing it — defensive.
    """
    if "trim" in spec and record.trim != spec["trim"]:
        return False
    if "body_style" in spec and record.body_style != spec["body_style"]:
        return False
    if "min_year" in spec and (record.year is None or record.year < spec["min_year"]):
        return False
    if "max_year" in spec and (record.year is None or record.year > spec["max_year"]):
        return False
    if "min_mileage" in spec and (record.mileage is None or record.mileage < spec["min_mileage"]):
        return False
    if "max_mileage" in spec and (record.mileage is None or record.mileage > spec["max_mileage"]):
        return False
    if "min_price" in spec and (record.mbusa_price is None or record.mbusa_price < spec["min_price"]):
        return False
    if "max_price_all_in" in spec and (record.mbusa_price is None or record.mbusa_price > spec["max_price_all_in"]):
        return False
    return True


def _matching_watchlist_labels(conn: sqlite3.Connection, record: ParsedRecord) -> list[str]:
    """Return labels of all active watchlist rows the record matches.
    OR-across-rows: any active 'spec' row matching is a hit."""
    rows = conn.execute(
        "SELECT spec_json, label FROM watchlist "
        "WHERE active = 1 AND kind = 'spec'"
    ).fetchall()
    matches = []
    for row in rows:
        try:
            spec = json.loads(row["spec_json"])
        except (TypeError, json.JSONDecodeError):
            continue  # malformed spec — skip rather than crash reconcile
        if _matches_spec(record, spec):
            matches.append(row["label"])
    return matches


# ---- Notification payload builders --------------------------------------

def _format_listing_line(r: ParsedRecord) -> str:
    """Single-line summary used in notification titles/bodies."""
    price = f"${r.mbusa_price:,}" if r.mbusa_price else "$?"
    miles = f"{r.mileage:,} mi" if r.mileage is not None else "? mi"
    yr = r.year or "?"
    dealer = r.dealer_name or "unknown dealer"
    return f"{yr} {r.trim or '?'} · {price} · {miles} · {dealer}"


def _percentile_line(conn, vin: str) -> str:
    """Inline-compute fair price for a VIN at notification time. New listings
    haven't been picked up by the nightly fairprice job yet, so cached values
    are stale or NULL — recomputing here costs ~1ms at 36 listings."""
    pct, tier = fairprice.compute_percentile(conn, vin)
    return fairprice.format_percentile(pct, tier)


def _year_trim_line(record: ParsedRecord) -> str:
    """e.g. '2025 E 450 4MATIC All-Terrain'."""
    parts = [str(record.year)] if record.year else []
    parts.append(record.model or record.trim or "")
    return " ".join(p for p in parts if p)


def _dealer_line(record: ParsedRecord) -> str:
    name = record.dealer_name or "—"
    state = record.dealer_state or "?"
    if record.dealer_distance_miles is not None:
        return f"{name} ({state} · {record.dealer_distance_miles:.0f} mi from 90210)"
    return f"{name} ({state})"


def _money(n: int | None) -> str:
    return f"${n:,}" if n is not None else "—"


def _miles(n: int | None) -> str:
    return f"{n:,}" if n is not None else "—"


def _notify_watchlist_match(conn, record: ParsedRecord, labels: list[str]) -> None:
    details = {
        "Asking": _money(record.mbusa_price),
        "Mileage": _miles(record.mileage),
        "Dealer": _dealer_line(record),
        "Color": f"{record.exterior_color or '?'} / {record.interior_color or '?'}",
        "Fair price": _percentile_line(conn, record.vin),
        "Body": f"Matches: {', '.join(labels)}",
    }
    notify.send(
        tier=1, event_type="watchlist_match",
        title=f"Watchlist hit: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin,
        url=record.dealer_site_url,
        image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


def _notify_price_drop_major(conn, record: ParsedRecord, old_price: int, pct: float) -> None:
    drop_pct = abs(pct) * 100
    delta = (record.mbusa_price or 0) - old_price
    details = {
        "Was": _money(old_price),
        "Now": f"**{_money(record.mbusa_price)}**",
        "Δ": f"{delta:+,} ({pct:+.2%})",
        "Mileage": _miles(record.mileage),
        "Dealer": _dealer_line(record),
        "Fair price": _percentile_line(conn, record.vin),
    }
    notify.send(
        tier=1, event_type="price_drop_major",
        title=f"Price drop {drop_pct:.1f}%: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin,
        url=record.dealer_site_url,
        image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


def _notify_reappeared(conn, record: ParsedRecord) -> None:
    details = {
        "Asking": _money(record.mbusa_price),
        "Mileage": _miles(record.mileage),
        "Dealer": _dealer_line(record),
        "Fair price": _percentile_line(conn, record.vin),
        "Body": "Was 'gone'; relisted on this poll.",
    }
    notify.send(
        tier=1, event_type="reappeared",
        title=f"Reappeared: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin,
        url=record.dealer_site_url,
        image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


# ---- Tier 2 (Pushover priority 0) ----------------------------------------

def _notify_new_listing_t2(conn, record: ParsedRecord) -> None:
    """Fires for ANY new listing. Suppressed if a Tier 1 watchlist_match
    already fired for this VIN in the same poll — see the call site."""
    details = {
        "Asking": _money(record.mbusa_price),
        "Mileage": _miles(record.mileage),
        "Dealer": _dealer_line(record),
        "Color": f"{record.exterior_color or '?'} / {record.interior_color or '?'}",
        "Fair price": _percentile_line(conn, record.vin),
    }
    notify.send(
        tier=2, event_type="new_listing",
        title=f"New: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin, url=record.dealer_site_url, image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


def _notify_price_drop_minor_t2(
    conn, record: ParsedRecord, old_price: int, pct: float,
) -> None:
    """3-7% drop. Tier 1 (-≥7%) takes precedence at the call site."""
    drop_pct = abs(pct) * 100
    delta = (record.mbusa_price or 0) - old_price
    details = {
        "Was": _money(old_price),
        "Now": _money(record.mbusa_price),
        "Δ": f"{delta:+,} ({pct:+.2%})",
        "Dealer": _dealer_line(record),
        "Fair price": _percentile_line(conn, record.vin),
    }
    notify.send(
        tier=2, event_type="price_drop_minor",
        title=f"Price drop {drop_pct:.1f}%: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin, url=record.dealer_site_url, image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


def _notify_dealer_change_t2(
    conn, record: ParsedRecord, old_dealer: str | None,
) -> None:
    details = {
        "From": old_dealer or "—",
        "To": _dealer_line(record),
        "Asking": _money(record.mbusa_price),
        "Body": "Same VIN at a new dealer (intra-network transfer).",
    }
    notify.send(
        tier=2, event_type="dealer_change",
        title=f"Dealer change: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin, url=record.dealer_site_url, image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


def _notify_mileage_anomaly_t2(
    conn, record: ParsedRecord, old_mileage: int,
) -> None:
    details = {
        "Was": _miles(old_mileage),
        "Now": _miles(record.mileage),
        "Δ": f"{(record.mileage or 0) - old_mileage:+,} mi",
        "Dealer": _dealer_line(record),
        "Body": "Mileage decreased on existing VIN — data anomaly worth knowing.",
    }
    notify.send(
        tier=2, event_type="mileage_anomaly",
        title=f"Mileage anomaly: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin, url=record.dealer_site_url, image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


# ---- Tier 3 (Pushover priority -2, silent in app history) ----------------

def _notify_gone_t3(conn, gone_row: dict) -> None:
    """A 'sold or de-listed' VIN. Silent — appears in Pushover history but
    no notification fires. Useful for the buying-decision audit trail."""
    last_known = (
        f"{gone_row.get('year') or '?'} {gone_row.get('trim') or '?'}"
    )
    details = {
        "Last dealer": gone_row.get("dealer_name") or "—",
        "Body": "VIN no longer in the active inventory feed.",
    }
    notify.send(
        tier=3, event_type="gone",
        title=f"Gone: {last_known} · {gone_row['vin']}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=gone_row["vin"],
        year_trim=last_known,
        details=details,
        conn=conn,
    )


def _notify_price_drop_silent_t3(
    conn, record: ParsedRecord, old_price: int, pct: float,
) -> None:
    """Sub-3% drop. Pushover priority -2 — appears in history, no alert."""
    drop_pct = abs(pct) * 100
    delta = (record.mbusa_price or 0) - old_price
    details = {
        "Was": _money(old_price),
        "Now": _money(record.mbusa_price),
        "Δ": f"{delta:+,} ({pct:+.2%})",
        "Dealer": _dealer_line(record),
    }
    notify.send(
        tier=3, event_type="price_drop_silent",
        title=f"Price drop {drop_pct:.2f}%: {_format_listing_line(record)}",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        vin=record.vin, url=record.dealer_site_url, image_url=record.photo_url,
        year_trim=_year_trim_line(record),
        details=details,
        conn=conn,
    )


# ---- Reconcile -----------------------------------------------------------

def reconcile(
    parsed_records: list[ParsedRecord],
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    dry_run: bool | None = None,
) -> dict:
    """Apply a scrape's parsed records to the DB. Returns events + stats.

    On health-check failure: writes a runs row with status='aborted', returns
    immediately, makes no other DB changes.

    DRY_RUN=1 (env or arg): all DB work happens in a transaction that is
    rolled back at the end. The returned events/stats describe what *would*
    have been written.
    """
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN") == "1"
    # observed_at provenance: a single timestamp is reused for all DB writes
    # in this run (listings.first_seen/last_seen, price_history.observed_at,
    # runs.started_at). Callers should pass `now` from when the API response
    # was received — run.py captures it just before fetch_all() so receive
    # time and write time stay close. The datetime.now() fallback exists for
    # tests; in production it would be write-time, which drifts if reconcile
    # is slow.
    started_at = now or datetime.now(timezone.utc)
    found = len(parsed_records)

    last_count = _last_successful_count(conn)

    # Health check
    if found == 0 or (last_count is not None and found < 0.5 * last_count):
        reason = (
            f"listings_found={found}; last successful run had {last_count}. "
            f"Threshold: must be > {0.5 * last_count if last_count else 0:.1f}."
        )
        finished_at = datetime.now(timezone.utc)
        run_id = _insert_run(
            conn,
            started_at=started_at, finished_at=finished_at,
            listings_found=found, duration_ms=_ms(started_at, finished_at),
            status="aborted", error_message=reason,
        )
        conn.commit()  # always commit the runs row even on abort
        return {
            "status": "aborted",
            "aborted_reason": reason,
            "events": [{"type": "aborted", "reason": reason}],
            "stats": _empty_stats(found, started_at, finished_at),
            "run_id": run_id,
        }

    events: list[dict] = []
    new_count = 0
    changed_count = 0
    gone_count = 0
    reappeared_count = 0

    seen_vins = {r.vin for r in parsed_records}
    existing = {row["vin"]: row for row in conn.execute("SELECT * FROM listings")}

    for record in parsed_records:
        existing_row = existing.get(record.vin)

        if existing_row is None:
            # New listing
            _insert_listing(conn, record, started_at)
            # Skip the initial price_history row if the API didn't give us a
            # price (or returned 0 — which scrape.py already mapped to None
            # since CPO wagons are never $0). The next poll with a real price
            # will populate price_history, and from then on the diff path
            # works normally.
            if record.mbusa_price is not None and record.mileage is not None:
                _insert_price_history(
                    conn, record.vin, started_at,
                    record.mbusa_price, record.mileage,
                )
            events.append({"type": "new", "vin": record.vin, "record": record})
            new_count += 1

            # Tier 1: watchlist match. Fire only on the first sighting.
            labels = _matching_watchlist_labels(conn, record)
            if labels:
                events.append({
                    "type": "watchlist_match", "vin": record.vin,
                    "record": record, "labels": labels,
                })
                _notify_watchlist_match(conn, record, labels)
            else:
                # Tier 2: any new listing that didn't already trigger Tier 1.
                # Skipping when watchlist matched avoids stacking two alerts
                # for the same VIN on the same poll — Tier 1 is louder and
                # already conveys the news.
                _notify_new_listing_t2(conn, record)
            continue

        # Existing — collect updates
        updates: dict[str, Any] = {"last_seen": started_at}

        # Status transitions
        if existing_row["status"] == "gone":
            updates["status"] = "reappeared"
            updates["gone_at"] = None
            events.append({"type": "reappeared", "vin": record.vin, "record": record})
            reappeared_count += 1
            # Tier 1: reappeared VIN.
            _notify_reappeared(conn, record)
        elif existing_row["status"] == "reappeared":
            # Promote on next sighting so the alert doesn't fire forever
            updates["status"] = "active"

        # Dealer change (intra-network transfer)
        if existing_row["dealer_name"] != record.dealer_name:
            old_dealer = existing_row["dealer_name"]
            events.append({
                "type": "dealer_change",
                "vin": record.vin,
                "old_dealer_name": old_dealer,
                "new_dealer_name": record.dealer_name,
                "record": record,
            })
            updates["dealer_name"] = record.dealer_name
            updates["dealer_zip"] = record.dealer_zip
            updates["dealer_state"] = record.dealer_state
            changed_count += 1
            # Tier 2: dealer changed for the same VIN.
            _notify_dealer_change_t2(conn, record, old_dealer)

        # Price / mileage change → append to price_history. Skip entirely
        # when the current scrape's price is missing/zero (API anomaly) —
        # we'd rather lose one data point than pollute price_history with
        # a row that future LAG comparisons read as a 100% drop.
        if record.mbusa_price is None or record.mileage is None:
            _update_listing(conn, record.vin, updates)
            continue

        last = _last_price_row(conn, record.vin)
        price_changed = last is None or last["price"] != record.mbusa_price
        mileage_changed = last is None or last["mileage"] != record.mileage

        if price_changed or mileage_changed:
            _insert_price_history(
                conn, record.vin, started_at,
                record.mbusa_price, record.mileage,
            )
            if last is not None:
                # The percentage-change calc requires a non-zero baseline.
                # A prior price of 0 (anomaly) would yield −∞ or 100% drop;
                # treat it as "recovered, count the change but skip the
                # event" — pct is meaningless from a 0 baseline.
                prior_price = last["price"]
                if (
                    price_changed
                    and prior_price is not None and prior_price > 0
                ):
                    pct = (record.mbusa_price - prior_price) / prior_price
                    events.append({
                        "type": "price_change",
                        "vin": record.vin,
                        "old_price": prior_price,
                        "new_price": record.mbusa_price,
                        "pct_change": pct,  # negative = drop
                        "record": record,
                    })
                    changed_count += 1
                    # Tiered routing for price drops. Mutually exclusive
                    # branches — a 10% drop fires Tier 1, not Tier 1+2+3.
                    if pct <= PRICE_DROP_TIER1_THRESHOLD:
                        _notify_price_drop_major(conn, record, prior_price, pct)
                    elif pct <= PRICE_DROP_TIER2_THRESHOLD:
                        _notify_price_drop_minor_t2(conn, record, prior_price, pct)
                    elif pct < 0:
                        _notify_price_drop_silent_t3(conn, record, prior_price, pct)
                    # pct >= 0 (increase or flat): no notification
                elif price_changed:
                    # Recovery from a zero/missing prior price. Count the
                    # change so runs.changed_count reflects DB-level activity,
                    # but don't fire any event.
                    changed_count += 1
                if (
                    mileage_changed
                    and last["mileage"] is not None
                    and record.mileage < last["mileage"]
                ):
                    old_mileage = last["mileage"]
                    events.append({
                        "type": "mileage_decrease",
                        "vin": record.vin,
                        "old_mileage": old_mileage,
                        "new_mileage": record.mileage,
                        "record": record,
                    })
                    changed_count += 1
                    # Tier 2: mileage went down — likely an odometer correction
                    # or data anomaly. Worth knowing about either way.
                    _notify_mileage_anomaly_t2(conn, record, old_mileage)

        _update_listing(conn, record.vin, updates)

    # Vanished VINs → 'gone'
    for vin, row in existing.items():
        if vin in seen_vins:
            continue
        if row["status"] == "gone":
            continue
        _update_listing(conn, vin, {"status": "gone", "gone_at": started_at})
        gone_row = dict(row)
        events.append({"type": "gone", "vin": vin, "old_record": gone_row})
        gone_count += 1
        # Tier 3: silent record in Pushover history. Useful for the
        # buying-decision audit trail without interrupting the user.
        _notify_gone_t3(conn, gone_row)

    finished_at = datetime.now(timezone.utc)
    duration_ms = _ms(started_at, finished_at)

    run_id = _insert_run(
        conn,
        started_at=started_at, finished_at=finished_at,
        listings_found=found,
        new_count=new_count, changed_count=changed_count,
        gone_count=gone_count, reappeared_count=reappeared_count,
        duration_ms=duration_ms, status="ok",
    )

    if dry_run:
        conn.rollback()
    else:
        conn.commit()

    return {
        "status": "ok",
        "aborted_reason": None,
        "events": events,
        "stats": {
            "listings_found": found,
            "new_count": new_count,
            "changed_count": changed_count,
            "gone_count": gone_count,
            "reappeared_count": reappeared_count,
            "duration_ms": duration_ms,
        },
        "run_id": run_id,
    }


# ---- helpers -------------------------------------------------------------

def _ms(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() * 1000)


def _empty_stats(found: int, start: datetime, end: datetime) -> dict:
    return {
        "listings_found": found,
        "new_count": 0,
        "changed_count": 0,
        "gone_count": 0,
        "reappeared_count": 0,
        "duration_ms": _ms(start, end),
    }
