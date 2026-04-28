"""Cross-source price check against the dealer's own website.

Per PROJECT.md "Cross-source price discrepancy detection (the Feb 11
lesson)": when MBUSA's portal and the dealer's own site disagree on a
VIN's asking price, that's the strongest negotiation leverage available
— the dealer can't defend the gap because it's their own brand's
inventory system contradicting them.

The MBUSA API gives us only the dealer's homepage URL, not a per-VIN
listing URL on the dealer's site. So this extractor takes a homepage,
fetches it, and looks for the VIN string. If the VIN appears, we look
for plausibly-priced `$XX,XXX` patterns nearby and return the most
common one (header / sidebar / main display all show the same price
on most dealer.com templates → most-frequent-wins is a decent heuristic).

This is intentionally simple. Real-world performance varies wildly by
dealer template; many dealer pages render inventory client-side via JS,
in which case the VIN won't appear in the initial HTML and we return
None. Per PROJECT.md: "A best-effort fetch is fine; log failures and
move on." Per-dealer parsers can be added later when specific dealers
prove worth the effort.
"""
from __future__ import annotations

import re
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "mb-wagon-watcher/1.0 (personal research; pwysocan@gmail.com)"
TIMEOUT_S = 10
PRICE_RE = re.compile(r"\$\s?([\d]{2,3}(?:,\d{3})+)")  # $XX,XXX or $X,XXX,XXX
SEARCH_WINDOW = 2_000  # chars around the VIN to scan for prices

# Plausible CPO E-Class wagon price range. Anything outside is filtered as
# noise (a $9,995 doc fee or a $250,000 unrelated supercar).
MIN_REASONABLE_PRICE = 30_000
MAX_REASONABLE_PRICE = 200_000


def candidate_urls(vin: str, dealer_url: str) -> list[str]:
    """URL patterns to try in order, most-specific first.

    Most dealer.com-template sites accept VIN-search URLs that pre-filter
    to one listing — those are far more likely to put the VIN string in
    the initial HTML than the dealer's homepage. Falls back to the
    homepage as a last resort.

    Examples (the prefixes vary by dealer template; we try the common ones):
      - https://www.example.com/inventory/used-Mercedes-Benz?vin=W1KLH...
      - https://www.example.com/inventory/?search=W1KLH...
      - https://www.example.com/  (homepage; works on a few simple sites)
    """
    base = dealer_url.rstrip("/")
    return [
        f"{base}/inventory/used-Mercedes-Benz?vin={vin}",
        f"{base}/inventory/?search={vin}",
        f"{base}/used/?vin={vin}",
        base,
    ]


def _fetch_impl(url: str, timeout: float = TIMEOUT_S) -> str | None:
    """Fetch a URL and return the body, or None on any failure."""
    if not url:
        return None
    req = Request(url, headers={"Accept": "text/html", "User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — best-effort
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError):
        return None


def fetch(url: str, timeout: float = TIMEOUT_S) -> str | None:
    """Public alias — see _fetch_impl. Conftest mocks this to a no-op so
    tests don't accidentally hit dealer sites; tests of the real fetch
    logic call _fetch_impl directly with a monkeypatched urlopen."""
    return _fetch_impl(url, timeout=timeout)


def _extract_price_near_vin(html: str, vin: str) -> int | None:
    """Find the most plausible asking price near the VIN in the HTML."""
    vin_pos = html.find(vin)
    if vin_pos < 0:
        return None

    start = max(0, vin_pos - SEARCH_WINDOW)
    end = min(len(html), vin_pos + SEARCH_WINDOW)
    window = html[start:end]

    candidates: list[int] = []
    for match in PRICE_RE.findall(window):
        try:
            n = int(match.replace(",", ""))
        except ValueError:
            continue
        if MIN_REASONABLE_PRICE <= n <= MAX_REASONABLE_PRICE:
            candidates.append(n)

    if not candidates:
        return None

    # Most-frequent wins (header + sidebar + main usually echo the same price).
    return Counter(candidates).most_common(1)[0][0]


def _check_impl(vin: str, dealer_url: str) -> tuple[int | None, str | None]:
    """Real implementation. Tests call this directly to bypass the
    conftest autouse mock on `check`.

    Tries each candidate URL in order until one returns a body that
    actually contains the VIN. Returns the price + the URL that worked
    (so listings.dealer_site_url reflects what was scraped, not just the
    homepage we started from). If no candidate yields a VIN match, returns
    (None, dealer_url) — the homepage is preserved as a "best we tried"
    record."""
    if not dealer_url or not vin:
        return None, None

    for candidate in candidate_urls(vin, dealer_url):
        html = fetch(candidate)
        if html is None:
            continue
        if vin not in html:
            continue
        price = _extract_price_near_vin(html, vin)
        return price, candidate

    # No candidate found the VIN. Return the homepage URL as the placeholder.
    return None, dealer_url


def check(vin: str, dealer_url: str) -> tuple[int | None, str | None]:
    """Best-effort cross-source price check for `vin` on `dealer_url`.

    Returns (dealer_site_price, fetched_url). Either component may be
    None — the URL is None only if dealer_url itself was empty; the price
    is None on fetch failure, no VIN match, or unreasonable values.
    Never raises.
    """
    return _check_impl(vin, dealer_url)
