"""Tests for vin_decode.py — NHTSA vPIC client.

Calls _decode_impl directly to bypass the autouse conftest mock that replaces
the public `decode` name."""
import json
from urllib.error import HTTPError, URLError

import pytest

import vin_decode
from vin_decode import _decode_impl


def _mock_response(payload: dict, status: int = 200):
    """Build a urlopen-like callable returning the given JSON payload."""
    body = json.dumps(payload).encode()

    class _Resp:
        def __init__(self):
            self.status = status

        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return lambda req, timeout: _Resp()


def test_decode_returns_parsed_json_on_200(monkeypatch):
    payload = {
        "Count": 1, "Message": "ok",
        "Results": [{"Variable": "Make", "Value": "MERCEDES-BENZ"}],
    }
    monkeypatch.setattr(vin_decode, "urlopen", _mock_response(payload))
    assert _decode_impl("W1KLH6FB6SA153938") == payload


def test_decode_returns_none_on_http_error(monkeypatch):
    def raise_http(req, timeout):
        raise HTTPError(req.full_url, 500, "Server Error", {}, None)
    monkeypatch.setattr(vin_decode, "urlopen", raise_http)
    assert _decode_impl("W1KLH6FB6SA153938") is None


def test_decode_returns_none_on_url_error(monkeypatch):
    def raise_url(req, timeout):
        raise URLError("dns failure")
    monkeypatch.setattr(vin_decode, "urlopen", raise_url)
    assert _decode_impl("W1KLH6FB6SA153938") is None


def test_decode_returns_none_on_invalid_json(monkeypatch):
    class _Garbage:
        status = 200

        def read(self):
            return b"not json{"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(vin_decode, "urlopen", lambda req, timeout: _Garbage())
    assert _decode_impl("W1KLH6FB6SA153938") is None


def test_decode_returns_none_on_non_200(monkeypatch):
    monkeypatch.setattr(vin_decode, "urlopen", _mock_response({}, status=503))
    assert _decode_impl("W1KLH6FB6SA153938") is None


def test_decode_skips_in_dry_run(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")

    def fail_if_called(*a, **kw):
        pytest.fail("urlopen should not be called in DRY_RUN")

    monkeypatch.setattr(vin_decode, "urlopen", fail_if_called)
    assert _decode_impl("W1KLH6FB6SA153938") is None
