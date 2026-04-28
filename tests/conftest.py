"""Test-wide defaults for the wagon-watcher suite."""
import pytest


@pytest.fixture(autouse=True)
def _suppress_pushover(monkeypatch, tmp_path_factory):
    """Default every test to PUSHOVER_ENABLED=false so notify.send() never
    actually POSTs to api.pushover.net. Tests that specifically exercise the
    live POST path can monkeypatch.setenv('PUSHOVER_ENABLED', 'true') and
    monkeypatch the network function as well.

    Also redirects notify.ALERTS_DIR to an isolated tmp directory so a test
    that exercises the success path (mock _post → True) doesn't pollute the
    repo's real alerts/ folder. Tests that specifically need to inspect the
    alert-log files override this with their own monkeypatch.setattr."""
    monkeypatch.setenv("PUSHOVER_ENABLED", "false")
    import notify
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path_factory.mktemp("alerts"))
