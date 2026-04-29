"""Daily digest generator. Pure markdown.

Per HANDOFF_daily_digest.md: a once-a-day digest committed to
digest/daily/<YYYY-MM-DD>.md (plus digest/daily/LATEST.md as the
stable phone-readable URL). Six sections in fixed order:

    § Population
    § Movers
    § Floor watch
    § Anomalies
    § Watchlist matches
    § Decision queue

The cron lands at 12:00 UTC = 05:00 PT during PDT / 04:00 PT during
PST. Read on phone via GitHub mobile.

Three optional config files in `config/`:
    disqualified_vins.json  — {"<vin>": "<reason>"}
    vin_annotations.json    — {"<vin>": "<note>"}
    decision_queue.json     — [{"vin", "action", "opened_at", "closed_at"}]

All three are optional — missing files render as bare/empty.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import connect, migrate
from reconcile import _matching_watchlist_labels
from scrape import ParsedRecord

ROOT = Path(__file__).parent
DAILY_DIGEST_DIR = ROOT / "digest" / "daily"
CONFIG_DIR = ROOT / "config"

DISQUALIFIED_VINS_FILE = "disqualified_vins.json"
VIN_ANNOTATIONS_FILE = "vin_annotations.json"
DECISION_QUEUE_FILE = "decision_queue.json"

POOL_FLOOR = 30  # listings_found below this is anomalous (typical pool ≈36)
SLOW_RUN_MS = 60_000  # cron run >60s is anomalous


# ---- helpers --------------------------------------------------------------

def _load_json_safe(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _money(n: int | None) -> str:
    if n is None:
        return "—"
    return f"${n:,.0f}"


def _signed(n: int) -> str:
    if n > 0:
        return f"+${n:,}"
    if n < 0:
        return f"-${abs(n):,}"
    return "$0"


def _shortdealer(name: str | None, max_chars: int = 22) -> str:
    if not name:
        return "—"
    name = (
        name
        .replace("Mercedes-Benz of ", "MB ")
        .replace(", LLC", "")
        .replace(", Ltd.", "")
    )
    return name if len(name) <= max_chars else name[: max_chars - 1] + "…"


def _dealer_loc(name: str | None, state: str | None) -> str:
    short = _shortdealer(name)
    if state:
        return f"{short}, {state}"
    return short


def _row_to_parsed_record(row) -> ParsedRecord:
    """Adapter so reconcile._matching_watchlist_labels can match against a
    listings-table row. Same pattern as run.py's adapter."""
    return ParsedRecord(
        vin=row["vin"],
        year=row["year"],
        model=row["model"] if "model" in row.keys() else None,
        trim=row["trim"],
        body_style=row["body_style"] if "body_style" in row.keys() else None,
        mbusa_price=(
            row["current_price"]
            if "current_price" in row.keys()
            else None
        ),
        mileage=row["mileage_first_seen"],
        exterior_color=None,
        exterior_color_code=None,
        interior_color=None,
        engine=None,
        is_certified=None,
        dealer_id=None,
        dealer_name=row["dealer_name"],
        dealer_zip=None,
        dealer_state=row["dealer_state"],
        dealer_distance_miles=None,
        dealer_site_url=None,
        photo_url=None,
        stock_id=None,
        options_json=None,
    )


# ---- section: header / footer --------------------------------------------

def _header(when: datetime) -> str:
    label = when.strftime("%Y-%m-%d")
    return "\n".join([
        "# mb-wagon-watcher · daily digest",
        "",
        f"**{label}** · 05:00 PT snapshot",
        "",
        f"`Generated: {when:%Y-%m-%dT%H:%M:%SZ}`",
    ])


def _footer(when: datetime) -> str:
    return "\n".join([
        "---",
        "",
        f"`mb-wagon-watcher · digest_daily.py · {when:%Y-%m-%dT%H:%M:%SZ}`",
        "",
        "_To annotate a VIN: edit `config/vin_annotations.json`._  ",
        "_To disqualify a VIN: edit `config/disqualified_vins.json`._  ",
        "_To track a decision: edit `config/decision_queue.json`._",
    ])


# ---- § Population ---------------------------------------------------------

def _section_population(conn: sqlite3.Connection, when: datetime, config_dir: Path) -> str:
    active = conn.execute(
        "SELECT COUNT(*) AS c FROM listings "
        "WHERE status IN ('active', 'reappeared')"
    ).fetchone()["c"]

    yesterday = (when - timedelta(days=1)).isoformat()
    yesterday_active = conn.execute(
        "SELECT COUNT(*) AS c FROM listings "
        "WHERE first_seen <= ? "
        "  AND (gone_at IS NULL OR gone_at > ?)",
        (yesterday, yesterday),
    ).fetchone()["c"]

    net = active - yesterday_active
    net_str = (
        f"{net:+d} net since yesterday"
        if net != 0 else "no change since yesterday"
    )

    disqualified = _load_json_safe(config_dir / DISQUALIFIED_VINS_FILE, {})
    rows = conn.execute(
        "SELECT l.*, "
        "       (SELECT price FROM price_history "
        "        WHERE vin = l.vin AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS current_price "
        "FROM listings l WHERE l.status IN ('active', 'reappeared')"
    ).fetchall()
    matches = 0
    actionable = 0
    for row in rows:
        if _matching_watchlist_labels(conn, _row_to_parsed_record(row)):
            matches += 1
            if row["vin"] not in disqualified:
                actionable += 1

    suffix_match = "es" if matches != 1 else ""
    return "\n".join([
        "## § Population",
        "",
        f"**Population:** {active} active ({net_str}) · "
        f"{matches} watchlist match{suffix_match} · "
        f"{actionable} actionable",
    ])


# ---- § Movers ------------------------------------------------------------

def _section_movers(conn: sqlite3.Connection, when: datetime) -> str:
    cutoff = (when - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT * FROM ("
        "  SELECT vin, observed_at, price, "
        "         LAG(price) OVER (PARTITION BY vin ORDER BY observed_at, id) AS prev_price "
        "  FROM price_history WHERE price > 0"
        ") WHERE observed_at >= ? AND prev_price > 0",
        (cutoff,),
    ).fetchall()

    # Dedupe to one row per VIN — keep the LARGEST absolute % move within
    # the 24h window. A flippy VIN ($70k → $68k → $70k → $68k) would
    # otherwise flood the section with redundant lines.
    by_vin: dict[str, dict] = {}
    for r in rows:
        delta = r["price"] - r["prev_price"]
        if delta == 0:
            continue
        pct = delta / r["prev_price"]
        candidate = {
            "vin": r["vin"],
            "delta": delta,
            "pct": pct,
            "new_price": r["price"],
        }
        existing = by_vin.get(r["vin"])
        if existing is None or abs(pct) > abs(existing["pct"]):
            by_vin[r["vin"]] = candidate

    movers = sorted(by_vin.values(), key=lambda m: abs(m["pct"]), reverse=True)[:10]

    if not movers:
        return "## § Movers\n\n_No price moves in the last 24 hours._"

    lines = ["## § Movers", ""]
    for m in movers:
        meta = conn.execute(
            "SELECT dealer_name, dealer_state FROM listings WHERE vin = ?",
            (m["vin"],),
        ).fetchone()
        loc = _dealer_loc(meta["dealer_name"] if meta else None,
                          meta["dealer_state"] if meta else None)
        sign_pct = "+" if m["delta"] > 0 else "-"
        lines.append(
            f"- {m['vin']} — {loc} — {_money(m['new_price'])} "
            f"({_signed(m['delta'])} / {sign_pct}{abs(m['pct']) * 100:.2f}%)"
        )
    return "\n".join(lines)


# ---- § Floor watch -------------------------------------------------------

def _section_floor_watch(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT l.vin, l.dealer_name, l.dealer_state, "
        "       (SELECT price FROM price_history "
        "        WHERE vin = l.vin AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS current_price, "
        "       (SELECT MIN(price) FROM price_history "
        "        WHERE vin = l.vin AND price > 0) AS min_price, "
        "       (SELECT MAX(price) FROM price_history "
        "        WHERE vin = l.vin AND price > 0) AS max_price "
        "FROM listings l "
        "WHERE l.status IN ('active', 'reappeared')"
    ).fetchall()

    floors = [
        r for r in rows
        if r["current_price"] is not None
        and r["min_price"] is not None
        and r["current_price"] == r["min_price"]
        and r["min_price"] != r["max_price"]  # require some movement
    ]

    if not floors:
        return "## § Floor watch\n\n_No VINs at their all-time low today._"

    lines = ["## § Floor watch", ""]
    for r in floors[:5]:
        loc = _dealer_loc(r["dealer_name"], r["dealer_state"])
        lines.append(
            f"- {r['vin']} — {loc} — {_money(r['current_price'])} "
            f"(down from {_money(r['max_price'])} floor)"
        )
    if len(floors) > 5:
        lines.append("")
        lines.append(f"_… and {len(floors) - 5} more at floor._")
    return "\n".join(lines)


# ---- § Anomalies ----------------------------------------------------------

def _section_anomalies(conn: sqlite3.Connection, when: datetime) -> str:
    cutoff = (when - timedelta(hours=24)).isoformat()
    findings: list[str] = []

    flips = conn.execute(
        "SELECT vin, COUNT(*) AS c FROM notifications "
        "WHERE sent_at >= ? AND event_type IN ('gone', 'reappeared') "
        "GROUP BY vin HAVING COUNT(*) > 2",
        (cutoff,),
    ).fetchall()
    for f in flips:
        findings.append(
            f"VIN `{f['vin']}` toggled status {f['c']} times "
            f"(feed instability or price-testing)"
        )

    slow = conn.execute(
        "SELECT COUNT(*) AS c, MAX(duration_ms) AS m FROM runs "
        "WHERE started_at >= ? AND duration_ms > ?",
        (cutoff, SLOW_RUN_MS),
    ).fetchone()
    if slow["c"]:
        findings.append(
            f"{slow['c']} cron run{'s' if slow['c'] != 1 else ''} took >60s "
            f"(max {slow['m'] / 1000:.1f}s) — API slowness"
        )

    low = conn.execute(
        "SELECT COUNT(*) AS c, MIN(listings_found) AS m FROM runs "
        "WHERE started_at >= ? AND listings_found < ? AND status = 'ok'",
        (cutoff, POOL_FLOOR),
    ).fetchone()
    if low["c"]:
        findings.append(
            f"{low['c']} cron run{'s' if low['c'] != 1 else ''} returned "
            f"<{POOL_FLOOR} listings (min {low['m']}) — possible API cap"
        )

    new_dealers = conn.execute(
        "SELECT DISTINCT dealer_name FROM listings "
        "WHERE first_seen >= ? AND dealer_name IS NOT NULL "
        "  AND dealer_name NOT IN ("
        "    SELECT DISTINCT dealer_name FROM listings WHERE first_seen < ?"
        "  )",
        (cutoff, cutoff),
    ).fetchall()
    for d in new_dealers:
        findings.append(f"New dealer first-seen: {d['dealer_name']}")

    transfers = conn.execute(
        "SELECT vin FROM notifications "
        "WHERE event_type = 'dealer_change' AND sent_at >= ?",
        (cutoff,),
    ).fetchall()
    for t in transfers:
        findings.append(
            f"VIN `{t['vin']}` moved between dealers (intra-network transfer)"
        )

    if not findings:
        return "## § Anomalies\n\n_No anomalies detected in the last 24h._"

    return "## § Anomalies\n\n" + "\n".join(f"- {f}" for f in findings)


# ---- § Watchlist matches -------------------------------------------------

def _section_watchlist_matches(conn: sqlite3.Connection, config_dir: Path) -> str:
    # Pull current_price into the row so the watchlist matcher can evaluate
    # max_price_all_in. SELECT * from listings alone leaves it None (price
    # lives in price_history), and a None price fails the spec defensively.
    rows = conn.execute(
        "SELECT l.*, "
        "       (SELECT price FROM price_history "
        "        WHERE vin = l.vin AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS current_price "
        "FROM listings l "
        "WHERE l.status IN ('active', 'reappeared') "
        "ORDER BY l.distance_miles ASC, l.last_seen DESC"
    ).fetchall()

    disqualified = _load_json_safe(config_dir / DISQUALIFIED_VINS_FILE, {})
    annotations = _load_json_safe(config_dir / VIN_ANNOTATIONS_FILE, {})

    lines = ["## § Watchlist matches", ""]
    found_any = False
    for row in rows:
        labels = _matching_watchlist_labels(conn, _row_to_parsed_record(row))
        if not labels:
            continue
        found_any = True
        latest = conn.execute(
            "SELECT price FROM price_history WHERE vin = ? AND price > 0 "
            "ORDER BY observed_at DESC, id DESC LIMIT 1",
            (row["vin"],),
        ).fetchone()
        price = latest["price"] if latest else None

        loc = _dealer_loc(row["dealer_name"], row["dealer_state"])
        suffix = ""
        if row["vin"] in disqualified:
            suffix = f" — DISQUALIFIED ({disqualified[row['vin']]})"
        elif row["vin"] in annotations:
            suffix = f" — {annotations[row['vin']]}"
        lines.append(f"- {row['vin']} — {loc} — {_money(price)}{suffix}")

    if not found_any:
        return "## § Watchlist matches\n\n_No active watchlist matches._"
    return "\n".join(lines)


# ---- § Decision queue ----------------------------------------------------

def _section_decision_queue(when: datetime, config_dir: Path) -> str:
    queue = _load_json_safe(config_dir / DECISION_QUEUE_FILE, [])
    open_items = [item for item in queue if not item.get("closed_at")]

    if not open_items:
        return (
            "## § Decision queue\n\n"
            "_No decisions in queue._  "
            "_Add one with: edit `config/decision_queue.json`._"
        )

    lines = ["## § Decision queue", "", "Open decisions today:"]
    for item in open_items:
        opened_str = item.get("opened_at", "")
        try:
            opened = datetime.fromisoformat(opened_str)
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            days = max(0, (when - opened).days)
            pending = f"{days} day{'s' if days != 1 else ''} pending"
        except (ValueError, TypeError):
            pending = "open"
        vin = item.get("vin", "—")
        action = item.get("action", "—")
        lines.append(f"- `{vin}` — {action} ({pending})")
    return "\n".join(lines)


# ---- top-level -----------------------------------------------------------

def generate_daily_digest(
    conn: sqlite3.Connection,
    when: datetime | None = None,
    *,
    config_dir: Path = CONFIG_DIR,
) -> str:
    when = when or datetime.now(timezone.utc)
    sections = [
        _header(when),
        _section_population(conn, when, config_dir),
        _section_movers(conn, when),
        _section_floor_watch(conn),
        _section_anomalies(conn, when),
        _section_watchlist_matches(conn, config_dir),
        _section_decision_queue(when, config_dir),
        _footer(when),
    ]
    return "\n\n---\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate today's daily digest.")
    parser.add_argument("--out-dir", type=Path, default=DAILY_DIGEST_DIR)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--when", help="ISO timestamp to use as 'now' (testing)")
    args = parser.parse_args(argv)

    when = (
        datetime.fromisoformat(args.when)
        if args.when else datetime.now(timezone.utc)
    )
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    conn = connect()
    try:
        migrate(conn)
        markdown = generate_daily_digest(conn, when=when, config_dir=args.config_dir)
    finally:
        conn.close()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    label = when.strftime("%Y-%m-%d")
    dated = args.out_dir / f"{label}.md"
    latest = args.out_dir / "LATEST.md"
    dated.write_text(markdown)
    latest.write_text(markdown)
    print(f"daily-digest: wrote {dated} and {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
