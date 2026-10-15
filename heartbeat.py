"""Alert when the watcher stops running.

The watcher's failure modes are not all loud. A GitHub Actions `schedule`
trigger is best-effort: on 2026-08-27 the every-30-minutes cron silently
degraded to roughly twice a day. Every run that did fire succeeded, so no
failure notification ever fired — the only symptom was runs that weren't
there. This module supplies the missing signal: it looks at how long ago
the last successful run happened and alerts if that gap is too large.

Runs from its own low-frequency workflow, deliberately separate from
`watch.yml` — a stall check that lives inside the thing being checked
cannot fire when that thing stops.

A second check covers partial degradation: if fewer than CADENCE_MIN_RUNS
successful runs landed in the trailing 24h, send one Tier 1 "watcher
degraded" alert per CADENCE_COOLDOWN_H.

Env:
  STALE_AFTER_HOURS   alert when the newest ok run is older than this (18)
  STALE_COOLDOWN_H    minimum spacing between stall alerts (12)
  CADENCE_MIN_RUNS    degraded below this many ok runs per 24h (10)
  CADENCE_COOLDOWN_H  minimum spacing between degraded alerts (24)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import notify
from db import connect

DEFAULT_STALE_AFTER_H = 18.0
DEFAULT_COOLDOWN_H = 12.0
EVENT_TYPE = "watcher_stalled"

DEFAULT_CADENCE_MIN_RUNS = 10
DEFAULT_CADENCE_COOLDOWN_H = 24.0
CADENCE_EVENT_TYPE = "watcher_degraded"


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_ok_run(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT started_at FROM runs WHERE status = 'ok' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return _parse(row["started_at"]) if row else None


def last_alert(conn: sqlite3.Connection, event_type: str) -> datetime | None:
    row = conn.execute(
        "SELECT sent_at FROM notifications WHERE event_type = ? "
        "ORDER BY sent_at DESC LIMIT 1",
        (event_type,),
    ).fetchone()
    return _parse(row["sent_at"]) if row else None


def last_stall_alert(conn: sqlite3.Connection) -> datetime | None:
    return last_alert(conn, EVENT_TYPE)


def check(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    stale_after_h: float | None = None,
    cooldown_h: float | None = None,
) -> dict:
    """Return a verdict dict; sends a Tier 1 alert when stalled and not
    inside the cooldown window. Never raises — a monitor that crashes is
    a monitor that lies."""
    now = now or datetime.now(timezone.utc)
    stale_after = timedelta(hours=stale_after_h if stale_after_h is not None
                            else float(os.environ.get("STALE_AFTER_HOURS", DEFAULT_STALE_AFTER_H)))
    cooldown = timedelta(hours=cooldown_h if cooldown_h is not None
                         else float(os.environ.get("STALE_COOLDOWN_H", DEFAULT_COOLDOWN_H)))

    last = last_ok_run(conn)
    if last is None:
        return {"stalled": False, "reason": "no successful run on record", "alerted": False}

    age = now - last
    if age <= stale_after:
        return {"stalled": False, "age_hours": age.total_seconds() / 3600, "alerted": False}

    prev = last_stall_alert(conn)
    if prev is not None and (now - prev) < cooldown:
        return {"stalled": True, "age_hours": age.total_seconds() / 3600,
                "alerted": False, "reason": "within cooldown"}

    hours = age.total_seconds() / 3600
    details = {
        "Last good run": last.strftime("%Y-%m-%d %H:%M UTC"),
        "Silent for": f"{hours:.1f} hours",
        "Threshold": f"{stale_after.total_seconds() / 3600:.0f} hours",
        "Body": ("The watcher has not completed a successful run recently. "
                 "GitHub `schedule` triggers are best-effort and can be "
                 "dropped silently — check the Actions tab, and re-trigger "
                 "with `gh workflow run watch.yml` if needed."),
    }
    notify.send(
        tier=1, event_type=EVENT_TYPE,
        title=f"Watcher stalled: no successful run in {hours:.0f}h",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        details=details,
        conn=conn,
    )
    return {"stalled": True, "age_hours": hours, "alerted": True}


def check_cadence(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    min_runs: int | None = None,
    window_h: float = 24.0,
    cooldown_h: float | None = None,
) -> dict:
    """Alert (Tier 1, at most once per cooldown) when fewer than `min_runs`
    successful watch runs landed in the trailing window.

    The stall check above only fires on total silence. The failure that
    actually happened — 2026-08-27 onward, 3–7 runs/day instead of ~40 — is
    a watcher that still runs, just too rarely to catch a fast-moving
    listing. Never raises, same as check()."""
    now = now or datetime.now(timezone.utc)
    min_runs = min_runs if min_runs is not None else int(
        os.environ.get("CADENCE_MIN_RUNS", DEFAULT_CADENCE_MIN_RUNS))
    cooldown = timedelta(hours=cooldown_h if cooldown_h is not None else float(
        os.environ.get("CADENCE_COOLDOWN_H", DEFAULT_CADENCE_COOLDOWN_H)))
    since = now - timedelta(hours=window_h)

    rows = conn.execute(
        "SELECT started_at FROM runs WHERE status = 'ok'"
    ).fetchall()
    if not rows:
        return {"degraded": False, "runs": 0, "alerted": False,
                "reason": "no successful run on record"}
    n = sum(1 for r in rows if since <= _parse(r["started_at"]) <= now)
    if n >= min_runs:
        return {"degraded": False, "runs": n, "alerted": False}

    prev = last_alert(conn, CADENCE_EVENT_TYPE)
    if prev is not None and (now - prev) < cooldown:
        return {"degraded": True, "runs": n, "alerted": False, "reason": "within cooldown"}

    details = {
        "Runs in last 24h": f"{n} (threshold {min_runs})",
        "Body": ("The watcher is running but too rarely to catch new listings "
                 "or sales quickly. GitHub `schedule` triggers are being "
                 "dropped — check that the launchd dispatch agent "
                 "(scripts/launchd/) is loaded, or trigger manually with "
                 "`gh workflow run watch.yml`."),
    }
    notify.send(
        tier=1, event_type=CADENCE_EVENT_TYPE,
        title=f"Watcher degraded: {n} runs in 24h",
        body="\n".join(f"{k}: {v}" for k, v in details.items()),
        details=details,
        conn=conn,
    )
    return {"degraded": True, "runs": n, "alerted": True}


def main(argv: list[str]) -> int:
    conn = connect()
    try:
        verdict = check(conn)
        cadence = check_cadence(conn)
    finally:
        conn.close()
    print(f"[heartbeat] {verdict} cadence={cadence}", file=sys.stderr)
    # Exit 0 even when stalled: the alert is the output, and a red workflow
    # here would be a second, noisier signal for the same condition.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
