"""Tests for dealer_site.py — best-effort cross-source price extractor.

Calls _fetch_impl / _extract_price_near_vin directly so the conftest
autouse mock on dealer_site.check / dealer_site.fetch doesn't get in
the way."""
from urllib.error import HTTPError, URLError

import pytest

import dealer_site
from dealer_site import _extract_price_near_vin, _fetch_impl


# ---- _extract_price_near_vin ---------------------------------------------

VIN = "W1KLH6FB6SA153938"


def test_extract_returns_none_when_vin_not_in_html():
    html = "<html><body><h1>$65,895</h1></body></html>"
    assert _extract_price_near_vin(html, VIN) is None


def test_extract_finds_price_near_vin():
    html = (
        f"<html><body><div>VIN: {VIN}</div>"
        f"<div class='price'>$65,895</div></body></html>"
    )
    assert _extract_price_near_vin(html, VIN) == 65_895


def test_extract_picks_most_common_when_repeated():
    """Most dealer.com templates show the asking price three times: header,
    sidebar, main display. Most-frequent wins."""
    html = (
        f"<header>$65,895</header>"
        f"<aside>$65,895</aside>"
        f"<main>VIN {VIN} $65,895 — $9,995 doc fee, $250,000 financing on a McLaren</main>"
    )
    assert _extract_price_near_vin(html, VIN) == 65_895


def test_extract_filters_unreasonable_prices():
    """Outside the 30k-200k window, drop the candidate."""
    html = (
        f"<div>{VIN}</div>"
        f"<div>$9,995 in fees</div>"
        f"<div>$250,000 financing</div>"
    )
    assert _extract_price_near_vin(html, VIN) is None


def test_extract_returns_none_on_no_dollar_signs():
    html = f"<html><body>{VIN} contact for price</body></html>"
    assert _extract_price_near_vin(html, VIN) is None


def test_extract_handles_six_figure_prices():
    """An AMG E63 wagon could legitimately be in the high 100s."""
    html = f"<div>{VIN}</div><div>$125,000</div>"
    assert _extract_price_near_vin(html, VIN) == 125_000


def test_extract_ignores_far_away_prices():
    """A VIN at byte 0 and a price 5,000 chars away (outside window) → None."""
    html = VIN + ("x" * 5000) + "$65,895" + ("x" * 1000)
    assert _extract_price_near_vin(html, VIN) is None


# ---- _fetch_impl ---------------------------------------------------------

def test_fetch_returns_body_on_200(monkeypatch):
    class _Resp:
        status = 200

        def read(self):
            return b"<html>ok</html>"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(dealer_site, "urlopen", lambda req, timeout: _Resp())
    assert _fetch_impl("https://example.com") == "<html>ok</html>"


def test_fetch_returns_none_on_http_error(monkeypatch):
    def raise_http(req, timeout):
        raise HTTPError(req.full_url, 500, "Server", {}, None)

    monkeypatch.setattr(dealer_site, "urlopen", raise_http)
    assert _fetch_impl("https://example.com") is None


def test_fetch_returns_none_on_url_error(monkeypatch):
    def raise_url(req, timeout):
        raise URLError("dns failure")

    monkeypatch.setattr(dealer_site, "urlopen", raise_url)
    assert _fetch_impl("https://example.com") is None


def test_fetch_returns_none_on_empty_url():
    assert _fetch_impl("") is None
    assert _fetch_impl(None) is None


# ---- check (high-level) --------------------------------------------------

def test_check_returns_none_none_on_empty_url():
    assert dealer_site._check_impl(VIN,"") == (None, None)
    assert dealer_site._check_impl(VIN,None) == (None, None)


def test_check_returns_none_url_on_failed_fetch(monkeypatch):
    """When fetch fails, return (None, url) — preserves the URL we tried so
    the listing's dealer_site_url column reflects that we attempted."""
    monkeypatch.setattr(dealer_site, "fetch", lambda url, timeout=10: None)
    price, url = dealer_site._check_impl(VIN,"https://example.com")
    assert price is None
    assert url == "https://example.com"


def test_check_returns_price_when_extractor_succeeds(monkeypatch):
    html = f"<div>{VIN}</div><div>$67,500</div>"
    monkeypatch.setattr(dealer_site, "fetch", lambda url, timeout=10: html)
    price, url = dealer_site._check_impl(VIN,"https://example.com")
    assert price == 67_500
    assert url == "https://example.com"
