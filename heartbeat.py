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

Env:
  STALE_AFTER_HOURS  alert when the newest ok run is older than this (18)
  STALE_COOLDOWN_H   minimum spacing between stall alerts (12)
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


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_ok_run(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT started_at FROM runs WHERE status = 'ok' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return _parse(row["started_at"]) if row else None


def last_stall_alert(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT sent_at FROM notifications WHERE event_type = ? "
        "ORDER BY sent_at DESC LIMIT 1",
        (EVENT_TYPE,),
    ).fetchone()
    return _parse(row["sent_at"]) if row else None


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


def main(argv: list[str]) -> int:
    conn = connect()
    try:
        verdict = check(conn)
    finally:
        conn.close()
    print(f"[heartbeat] {verdict}", file=sys.stderr)
    # Exit 0 even when stalled: the alert is the output, and a red workflow
    # here would be a second, noisier signal for the same condition.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
