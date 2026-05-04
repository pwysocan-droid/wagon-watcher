"""Weekly digest generator. Pure markdown.

Per PROJECT.md "Weekly digest": Sunday morning, generates `digest/YYYY-WW.md`
and commits it. Six numbered sections in the SBB-via-ECAL house style:

    01 — Headline counts
    02 — Watchlist hits
    03 — Price drops this week
    04 — Stalest active listings
    05 — Trend (4-week median asking)
    06 — Footnotes / build metadata

The runtime also writes `digest/LATEST.md` as a stable entry point — same
content as the dated file, but a fixed URL the user can hand to Opus chats:

    https://raw.githubusercontent.com/<owner>/<repo>/main/digest/LATEST.md

This module is read-only with respect to the DB. The only side effect is
writing two markdown files.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from db import connect, migrate
from scrape import mbusa_listing_url

ROOT = Path(__file__).parent
# Weekly digest writes to digest/weekly/ to mirror digest_daily.py's
# digest/daily/ convention and align with Vercel's /digest/weekly/<file>
# URL pattern. Files at the old digest/<file> path are no longer updated
# and were removed in the same commit that introduced this constant.
DIGEST_DIR = ROOT / "digest" / "weekly"


# ---- helpers --------------------------------------------------------------

def _money(n: int | float | None) -> str:
    if n is None:
        return "—"
    return f"${n:,.0f}"


def _signed_money(n: int | float | None) -> str:
    if n is None:
        return "—"
    return f"{'+' if n > 0 else '−' if n < 0 else ''}${abs(n):,.0f}"


def _signed_pct(p: float | None) -> str:
    if p is None:
        return "—"
    return f"{'+' if p > 0 else '−' if p < 0 else ''}{abs(p) * 100:.2f}%"


def _week_label(when: datetime) -> str:
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _human_date_range(start: datetime, end: datetime) -> str:
    return f"{start:%B %-d} → {end:%B %-d, %Y}"


def _shortdealer(name: str | None, max_chars: int = 22) -> str:
    if not name:
        return "—"
    name = name.replace("Mercedes-Benz of ", "MB ").replace(", LLC", "").replace(", Ltd.", "")
    return name if len(name) <= max_chars else name[: max_chars - 1] + "…"


# ---- section builders ----------------------------------------------------

def _header(when: datetime, start: datetime, end: datetime, conn: sqlite3.Connection) -> str:
    iso = when.isocalendar()
    runs_in_window = conn.execute(
        "SELECT COUNT(*) AS total, "
        "       SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok "
        "FROM runs WHERE started_at >= ? AND started_at < ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    total = runs_in_window["total"] or 0
    ok = runs_in_window["ok"] or 0

    return "\n".join([
        "# mb-wagon-watcher · weekly digest",
        "",
        f"**Week {iso.week} — {iso.year}**  ",
        _human_date_range(start, end),
        "",
        f"`Snapshot range: {start:%Y-%m-%dT%H:%MZ} → {end:%Y-%m-%dT%H:%MZ} · {total} runs · {ok} OK`  ",
        "`Source: nafta-service.mbusa.com/api/inv/v1/en_us/used/vehicles/search`  ",
        f"`Generated: {when:%Y-%m-%dT%H:%M:%SZ}`",
    ])


def _headline_counts(conn: sqlite3.Connection, start: datetime, end: datetime) -> str:
    agg = conn.execute(
        "SELECT COALESCE(SUM(new_count), 0) AS new_total, "
        "       COALESCE(SUM(changed_count), 0) AS changed_total, "
        "       COALESCE(SUM(gone_count), 0) AS gone_total, "
        "       COALESCE(SUM(reappeared_count), 0) AS reappeared_total "
        "FROM runs WHERE started_at >= ? AND started_at < ? AND status = 'ok'",
        (start.isoformat(), end.isoformat()),
    ).fetchone()

    watchlist_hits = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications "
        "WHERE event_type = 'watchlist_match' AND sent_at >= ? AND sent_at < ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()["c"]

    # Total $ in drops + count of dropping listings
    drops = _list_drops(conn, start, end)
    total_dropped = sum(-d["delta"] for d in drops)
    distinct_droppers = len({d["vin"] for d in drops})

    # Pool size: count of active+reappeared, end of window vs start of window
    pool_now = _pool_size_at(conn, end)
    pool_start = _pool_size_at(conn, start)

    # Median asking: this week vs last week
    median_now = _median_active_price_at(conn, end)
    median_last_week = _median_active_price_at(conn, end - timedelta(days=7))
    median_4_weeks = _median_active_price_at(conn, end - timedelta(days=28))

    pool_arrow = f"{pool_start} → {pool_now}" if pool_start != pool_now else f"{pool_now} (unchanged)"
    median_wk = (
        f"`{_money(median_last_week)} → {_money(median_now)}` wk/wk"
        if median_last_week is not None and median_now is not None
        else "wk/wk: insufficient data"
    )
    median_4 = (
        f"`{_money(median_4_weeks)} → {_money(median_now)}` over 4 weeks"
        if median_4_weeks is not None and median_now is not None
        else "over 4 weeks: insufficient data"
    )

    table = (
        "| New listings | Price changes | Sold / gone | Reappeared | Watchlist hits |\n"
        "|:-:|:-:|:-:|:-:|:-:|\n"
        f"| {agg['new_total']} | {agg['changed_total']} | {agg['gone_total']} | "
        f"{agg['reappeared_total']} | {watchlist_hits} |"
    )

    if total_dropped > 0:
        prose = (
            f"Total **{_money(total_dropped)}** in price reductions across "
            f"{distinct_droppers} listing{'s' if distinct_droppers != 1 else ''}. "
            f"Pool: `{pool_arrow}`; median asking moved {median_wk} and {median_4}."
        )
    else:
        prose = (
            f"No price reductions this week. Pool: `{pool_arrow}`; "
            f"median asking {median_wk}, {median_4}."
        )

    return "\n".join([
        "## § 01 — Headline counts",
        "",
        table,
        "",
        prose,
    ])


def _watchlist_hits(conn: sqlite3.Connection, start: datetime, end: datetime) -> str:
    rows = conn.execute(
        "SELECT vin, title, body, sent_at FROM notifications "
        "WHERE event_type = 'watchlist_match' AND sent_at >= ? AND sent_at < ? "
        "ORDER BY sent_at",
        (start.isoformat(), end.isoformat()),
    ).fetchall()

    if not rows:
        return "## § 02 — Watchlist hits\n\n_No watchlist matches this week._"

    lines = ["## § 02 — Watchlist hits", ""]
    for r in rows:
        body_indented = "\n".join(f"> {line}" for line in r["body"].splitlines())
        lines.append(f"> **{r['title']}**")
        lines.append(">")
        lines.append(body_indented)
        lines.append("")
    return "\n".join(lines).rstrip()


def _list_drops(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[dict]:
    """Return per-row price drops in the window. Each entry is a single
    price_history row that came in BELOW the prior observation for that VIN.

    The LAG window function must run over the FULL price_history (so it can
    see prior prices from before the window starts) — filter to the window
    in the outer query instead.

    Rows with price <= 0 are filtered out — those are API data anomalies
    (MBUSA briefly returned msrp=0 for ~10 records on 2026-04-26) and
    spurious 100%-drop rows would otherwise dominate the digest."""
    rows = conn.execute(
        "SELECT * FROM ("
        "  SELECT vin, observed_at, price, "
        "         LAG(price) OVER (PARTITION BY vin ORDER BY observed_at, id) AS prev_price "
        "  FROM price_history "
        "  WHERE price > 0"
        ") WHERE observed_at >= ? AND observed_at < ? AND prev_price > 0",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    drops = []
    for r in rows:
        if r["prev_price"] is None:
            continue
        delta = r["price"] - r["prev_price"]
        if delta < 0:
            drops.append({
                "vin": r["vin"], "observed_at": r["observed_at"],
                "old_price": r["prev_price"], "new_price": r["price"],
                "delta": delta,
                "pct": delta / r["prev_price"],
            })
    return drops


def _price_drops_table(conn: sqlite3.Connection, start: datetime, end: datetime) -> str:
    drops = _list_drops(conn, start, end)
    drops.sort(key=lambda d: d["pct"])  # most-negative pct first
    drops = drops[:5]

    if not drops:
        return "## § 03 — Price drops this week\n\n_No price drops this week._"

    # Enrich with listing data
    enriched = []
    for d in drops:
        meta = conn.execute(
            "SELECT year, dealer_name FROM listings WHERE vin = ?",
            (d["vin"],),
        ).fetchone()
        enriched.append({**d, "year": meta["year"] if meta else None,
                         "dealer": meta["dealer_name"] if meta else None})

    lines = [
        "## § 03 — Price drops this week",
        "",
        "| Year | Dealer | VIN | Was | Now | Δ |",
        "| ---- | ------ | --- | --: | --: | --: |",
    ]
    for d in enriched:
        lines.append(
            f"| {d['year'] or '—'} | {_shortdealer(d['dealer'])} | "
            f"[`{d['vin']}`]({mbusa_listing_url(d['vin'])}) | "
            f"{_money(d['old_price'])} | "
            f"**{_money(d['new_price'])}** | **{_signed_pct(d['pct'])}** |"
        )
    return "\n".join(lines)


def _stalest_listings(conn: sqlite3.Connection, when: datetime, limit: int = 5) -> str:
    rows = conn.execute(
        "SELECT l.vin, l.year, l.dealer_name, l.first_seen, "
        "       (SELECT price FROM price_history WHERE vin = l.vin AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS asking, "
        "       (SELECT COUNT(*) FROM price_history p1 "
        "        WHERE p1.vin = l.vin AND p1.price > 0 "
        "          AND p1.price < (SELECT p2.price FROM price_history p2 "
        "                          WHERE p2.vin = p1.vin AND p2.observed_at < p1.observed_at "
        "                            AND p2.price > 0 "
        "                          ORDER BY p2.observed_at DESC LIMIT 1)) AS drop_count "
        "FROM listings l "
        "WHERE l.status IN ('active', 'reappeared') "
        "ORDER BY l.first_seen ASC LIMIT ?",
        (limit,),
    ).fetchall()

    if not rows:
        return "## § 04 — Stalest active listings\n\n_No active listings._"

    lines = [
        "## § 04 — Stalest active listings",
        "",
        "| DoL | Year | Dealer | VIN | Asking | Drops |",
        "| --: | ---- | ------ | --- | --: | --: |",
    ]
    for r in rows:
        first_seen = datetime.fromisoformat(r["first_seen"])
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        days = (when - first_seen).days
        lines.append(
            f"| **{days}** | {r['year'] or '—'} | "
            f"{_shortdealer(r['dealer_name'])} | "
            f"[`{r['vin']}`]({mbusa_listing_url(r['vin'])}) | "
            f"{_money(r['asking'])} | {r['drop_count'] or 0} |"
        )
    return "\n".join(lines)


def _trend_line(conn: sqlite3.Connection, when: datetime) -> str:
    """Median active asking price at 4 weekly anchors ending at `when`."""
    medians = []
    for weeks_back in (3, 2, 1, 0):
        anchor = when - timedelta(days=7 * weeks_back)
        m = _median_active_price_at(conn, anchor)
        medians.append(m)

    if all(m is None for m in medians):
        return "## § 05 — Trend\n\n_Insufficient history for a 4-week median trend._"

    formatted = " → ".join(_money(m) if m is not None else "—" for m in medians)
    return "\n".join([
        "## § 05 — Trend",
        "",
        f"4-week median asking trend: `{formatted}`.",
    ])


def _median_active_price_at(conn: sqlite3.Connection, anchor: datetime) -> int | None:
    """Median of last-observed-price-per-VIN across listings that were
    active at `anchor`. Listings count as 'active' at anchor if first_seen
    <= anchor AND (gone_at IS NULL OR gone_at > anchor)."""
    rows = conn.execute(
        "SELECT (SELECT price FROM price_history "
        "        WHERE vin = l.vin AND observed_at <= ? AND price > 0 "
        "        ORDER BY observed_at DESC, id DESC LIMIT 1) AS price "
        "FROM listings l "
        "WHERE l.first_seen <= ? "
        "  AND (l.gone_at IS NULL OR l.gone_at > ?)",
        (anchor.isoformat(), anchor.isoformat(), anchor.isoformat()),
    ).fetchall()
    prices = [r["price"] for r in rows if r["price"] is not None]
    if not prices:
        return None
    return int(median(prices))


def _pool_size_at(conn: sqlite3.Connection, anchor: datetime) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM listings "
        "WHERE first_seen <= ? "
        "  AND (gone_at IS NULL OR gone_at > ?)",
        (anchor.isoformat(), anchor.isoformat()),
    ).fetchone()["c"]


def _footer(when: datetime) -> str:
    return "\n".join([
        "---",
        "",
        f"`mb-wagon-watcher · digest.py · {when:%Y-%m-%dT%H:%M:%SZ} · "
        "github.com/pwysocan-droid/wagon-watcher`",
    ])


# ---- top-level -----------------------------------------------------------

def generate(conn: sqlite3.Connection, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    end = when
    start = when - timedelta(days=7)

    sections = [
        _header(when, start, end, conn),
        _headline_counts(conn, start, end),
        _watchlist_hits(conn, start, end),
        _price_drops_table(conn, start, end),
        _stalest_listings(conn, when),
        _trend_line(conn, when),
        _footer(when),
    ]
    return "\n\n---\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the weekly digest.")
    parser.add_argument("--out-dir", type=Path, default=DIGEST_DIR,
                        help="Output directory (default: digest/)")
    parser.add_argument("--when", help="ISO timestamp to use as 'now' (for testing)")
    args = parser.parse_args(argv)

    when = datetime.fromisoformat(args.when) if args.when else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    conn = connect()
    try:
        migrate(conn)
        markdown = generate(conn, when=when)
    finally:
        conn.close()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    label = _week_label(when)
    dated = args.out_dir / f"{label}.md"
    latest = args.out_dir / "LATEST.md"
    dated.write_text(markdown)
    latest.write_text(markdown)

    print(f"digest: wrote {dated} and {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
