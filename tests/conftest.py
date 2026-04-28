"""Test-wide defaults for the wagon-watcher suite."""
import pytest


@pytest.fixture(autouse=True)
def _suppress_pushover(monkeypatch):
    """Default every test to PUSHOVER_ENABLED=false so notify.send() never
    actually POSTs to api.pushover.net. Tests that specifically exercise the
    live POST path can monkeypatch.setenv('PUSHOVER_ENABLED', 'true') and
    monkeypatch the network function as well."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "false")
