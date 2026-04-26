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
from datetime import datetime, timezone
from pathlib import Path

from db import DB_PATH, connect, migrate
from reconcile import reconcile
from scrape import RAW_SNAPSHOTS, fetch_all, parse_response, save_snapshot

ROOT = Path(__file__).parent
LATEST_JSON = ROOT / "data" / "latest.json"
COMMIT_MSG_FILE = ROOT / ".run-commit-msg.txt"

LATEST_COLUMNS = (
    "vin", "year", "model", "trim", "body_style",
    "exterior_color", "interior_color",
    "dealer_name", "dealer_state", "dealer_zip",
    "mileage_first_seen", "photo_url",
    "status", "first_seen", "last_seen",
)


def write_latest_json(conn, out_path: Path) -> Path:
    """Dump active+reappeared listings, sorted newest-first by last_seen."""
    rows = conn.execute(
        f"SELECT {', '.join(LATEST_COLUMNS)} FROM listings "
        "WHERE status IN ('active', 'reappeared') "
        "ORDER BY last_seen DESC, vin"
    ).fetchall()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "listings": [dict(r) for r in rows],
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
    finally:
        conn.close()

    msg = commit_message(result, started_at)
    commit_msg_file.write_text(msg + "\n")
    print(msg)

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
