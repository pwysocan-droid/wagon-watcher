"""Pushover dispatcher for wagon-watcher Tier 1/2/3 notifications.

Per HANDOFF_step5.md and PROJECT.md:
- Tier 1 + event_type='scraper_aborted' → priority 2 (retry=30, expire=3600)
- Tier 1 (other)                        → priority 1
- Tier 2                                → priority 0
- Tier 3                                → priority -2 (silent history only)

`send()` never raises. Every call is logged to the `notifications` table
(success or failure of the POST itself, or a synthetic "DRY_RUN" row when
disabled). When called with a `conn` argument, the INSERT joins that
connection's transaction and is committed/rolled back with it — this gives
reconcile.py atomicity (a rolled-back run leaves no orphan notification
rows). When called standalone, notify opens its own connection and commits.

DRY_RUN=1 or PUSHOVER_ENABLED=false suppresses the POST.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from db import connect

PUSHOVER_API = "https://api.pushover.net/1/messages.json"
TIMEOUT_S = 10
EMERGENCY_RETRY_S = 30
EMERGENCY_EXPIRE_S = 3600
CONNECTION_RETRIES = 1


def _priority_for(tier: int, event_type: str) -> tuple[int, dict]:
    """Map (tier, event_type) → (Pushover priority, extra POST fields).

    Priority 2 (emergency) requires retry+expire per Pushover's API.
    """
    if tier == 1 and event_type == "scraper_aborted":
        return 2, {"retry": EMERGENCY_RETRY_S, "expire": EMERGENCY_EXPIRE_S}
    if tier == 1:
        return 1, {}
    if tier == 2:
        return 0, {}
    if tier == 3:
        return -2, {}
    raise ValueError(f"unknown tier: {tier}")


def _dry_run_active() -> bool:
    if os.environ.get("DRY_RUN") == "1":
        return True
    enabled = os.environ.get("PUSHOVER_ENABLED", "true").lower()
    return enabled in ("false", "0", "no", "off")


def _post(payload: dict) -> tuple[bool, str]:
    """POST to Pushover. Returns (was_2xx, response_text_or_error_string).

    Retries CONNECTION_RETRIES times on URLError (network issue).
    Does NOT retry 4xx/5xx — those represent a server decision to reject.
    """
    body = urlencode(payload).encode("utf-8")
    req = Request(PUSHOVER_API, data=body, method="POST")

    last_err = "unknown error"
    for _ in range(CONNECTION_RETRIES + 1):
        try:
            with urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 — known endpoint
                text = resp.read().decode("utf-8")
                return (200 <= resp.status < 300), text
        except HTTPError as e:
            err_text = e.read().decode("utf-8") if e.fp else str(e)
            return False, err_text
        except URLError as e:
            last_err = f"URLError: {e.reason}"
            continue
    return False, last_err


def _log(
    conn: sqlite3.Connection,
    *,
    tier: int,
    event_type: str,
    vin: str | None,
    title: str,
    body: str,
    url: str | None,
    pushover_priority: int,
    pushover_response: str | None,
    success: bool,
    sent_at: datetime | None = None,
) -> None:
    """Insert one notification audit row. Caller commits the surrounding txn."""
    conn.execute(
        "INSERT INTO notifications "
        "(sent_at, tier, event_type, vin, title, body, url, "
        " pushover_priority, pushover_response, success) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sent_at or datetime.now(timezone.utc),
            tier, event_type, vin, title, body, url,
            pushover_priority, pushover_response,
            1 if success else 0,
        ),
    )


def send(
    tier: int,
    event_type: str,
    title: str,
    body: str,
    *,
    vin: str | None = None,
    url: str | None = None,
    image_url: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Send a Pushover notification and write an audit row.

    Returns True if either the POST returned 2xx OR we were in dry-run /
    disabled mode (the call completed without error). Returns False on
    missing credentials, 4xx/5xx, or network failure after retries.

    Never raises. Notification failures must not crash the reconciler.
    """
    try:
        priority, extras = _priority_for(tier, event_type)
    except ValueError as e:
        print(f"[notify] {e}", file=sys.stderr)
        return False

    own_conn = conn is None
    conn = conn or connect()

    try:
        if _dry_run_active():
            print(
                f"[notify DRY_RUN] tier={tier} event={event_type} "
                f"priority={priority} title={title!r}",
                file=sys.stderr,
            )
            _log(
                conn, tier=tier, event_type=event_type, vin=vin,
                title=title, body=body, url=url,
                pushover_priority=priority,
                pushover_response="DRY_RUN", success=False,
            )
            if own_conn:
                conn.commit()
            return True

        user = os.environ.get("PUSHOVER_USER_KEY")
        token = os.environ.get("PUSHOVER_API_TOKEN")
        if not user or not token:
            err = "missing PUSHOVER_USER_KEY or PUSHOVER_API_TOKEN"
            print(f"[notify] {err}", file=sys.stderr)
            _log(
                conn, tier=tier, event_type=event_type, vin=vin,
                title=title, body=body, url=url,
                pushover_priority=priority,
                pushover_response=err, success=False,
            )
            if own_conn:
                conn.commit()
            return False

        payload: dict = {
            "token": token, "user": user,
            "title": title[:250], "message": body[:1024],
            "priority": priority,
            **extras,
        }
        if url:
            payload["url"] = url
        if image_url:
            # Pushover natively supports remote-URL attachments — no multipart upload needed.
            payload["attachment_url"] = image_url

        ok, response_text = _post(payload)
        _log(
            conn, tier=tier, event_type=event_type, vin=vin,
            title=title, body=body, url=url,
            pushover_priority=priority,
            pushover_response=response_text[:8192],  # cap audit log size
            success=ok,
        )
        if own_conn:
            conn.commit()
        return ok
    finally:
        if own_conn:
            conn.close()


def _cli_test() -> int:
    """Send a real test notification. Used for end-to-end verification."""
    # Ensure the notifications table exists before send() tries to log to it.
    from db import migrate
    bootstrap = connect()
    try:
        migrate(bootstrap)
    finally:
        bootstrap.close()

    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok = send(
        tier=1, event_type="integration_test",
        title="wagon-watcher integration test",
        body=f"Test send at {when}. If you see this, notify.py is wired up.",
    )
    if ok:
        print("notify: test sent OK")
        return 0
    print("notify: test failed — check the notifications table for details")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--test", action="store_true",
                        help="Send a real test notification and exit")
    args = parser.parse_args()
    if args.test:
        sys.exit(_cli_test())
    parser.print_help()
    sys.exit(2)
