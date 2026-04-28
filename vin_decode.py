"""NHTSA vPIC VIN decoder. Best-effort; never raises out of decode().

Per PROJECT.md "VIN decode": on first sight of a new VIN, hit
    https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/<VIN>?format=json
and cache the full response in `listings.vin_decode_json`. The endpoint is
public, no auth, no meaningful rate limit at our volume (~1 call per new
VIN, days between new VINs).

The Results array is a list of {Variable, VariableId, Value} dicts. We
store the whole response — flexible for future queries (factory options,
recall flags, drivetrain spec) without committing to any particular shape
in our schema.

Failure modes are silent: if the network is down or NHTSA returns an
error envelope, decode() returns None and the caller stores NULL. The
listing still tracks; we just lack the decode for it. A later reconcile
run could re-attempt for VINs with NULL vin_decode_json — not built today.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

NHTSA_VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin"
TIMEOUT_S = 10
USER_AGENT = "mb-wagon-watcher/1.0 (personal research; pwysocan@gmail.com)"


def _decode_impl(vin: str, *, timeout: float = TIMEOUT_S) -> dict | None:
    """Real implementation. Tests call this directly; the public `decode`
    indirection lets conftest's autouse fixture replace `decode` with a
    no-op without affecting tests that exercise the real network logic."""
    if os.environ.get("DRY_RUN") == "1":
        return None
    url = f"{NHTSA_VPIC}/{vin}?format=json"
    req = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — known endpoint
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError):
        return None


def decode(vin: str, *, timeout: float = TIMEOUT_S) -> dict | None:
    """Return the raw NHTSA vPIC response for `vin`, or None on any error.

    Honors DRY_RUN=1 by skipping the network call (returns None).
    """
    return _decode_impl(vin, timeout=timeout)
