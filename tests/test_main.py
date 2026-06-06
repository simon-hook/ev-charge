"""Tests for threshold logic, notifier dispatch, and SoC detection. Fully mocked — no network."""

from __future__ import annotations

import pytest

from ev_charge import audi, main, notify
from ev_charge.audi import BatteryReading
from ev_charge.config import ConfigError, load_config


# --- fixtures --------------------------------------------------------------------------

@pytest.fixture
def ntfy_env(monkeypatch):
    """A complete, valid ntfy configuration in the environment."""
    env = {
        "AUDI_USERNAME": "me@example.com",
        "AUDI_PASSWORD": "secret",
        "AUDI_COUNTRY": "GB",
        "BATTERY_THRESHOLD": "40",
        "NOTIFY_BACKEND": "ntfy",
        "NTFY_TOPIC": "topic-123",
        "NTFY_SERVER": "https://ntfy.sh",
    }
    for key in (
        "AUDI_SPIN", "AUDI_VIN", "NOTIFY_ON_ERROR", "PUSHOVER_TOKEN", "PUSHOVER_USER",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


# --- config ----------------------------------------------------------------------------

def test_load_config_defaults(ntfy_env):
    cfg = load_config()
    assert cfg.threshold == 40
    assert cfg.backend == "ntfy"
    assert cfg.notify_on_error is False


def test_config_requires_topic_for_ntfy(ntfy_env, monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    with pytest.raises(ConfigError):
        load_config()


def test_config_rejects_unknown_backend(ntfy_env, monkeypatch):
    monkeypatch.setenv("NOTIFY_BACKEND", "carrier-pigeon")
    with pytest.raises(ConfigError):
        load_config()


# --- threshold / alerting logic --------------------------------------------------------

def _patch_reading(monkeypatch, soc):
    reading = BatteryReading(soc=soc, vin="WAUZZZ123", raw={})
    monkeypatch.setattr(main, "fetch_battery", _async_return(reading))


def _async_return(value):
    async def _coro(_cfg):
        return value
    return _coro


@pytest.mark.parametrize(
    "soc,argv,expect_alert",
    [
        (35, [], True),    # below threshold -> alert
        (40, [], False),   # exactly at threshold -> no alert (strictly below)
        (80, [], False),   # well above -> no alert
        (90, ["--force"], True),  # --force overrides level
    ],
)
def test_alert_threshold(ntfy_env, monkeypatch, soc, argv, expect_alert):
    _patch_reading(monkeypatch, soc)
    sent = []
    monkeypatch.setattr(main.notify, "send", lambda cfg, title, msg: sent.append((title, msg)))

    rc = main.run(argv)

    assert rc == 0
    assert bool(sent) is expect_alert
    if expect_alert:
        assert f"{soc}%" in sent[0][1]


def test_audi_error_returns_nonzero_and_optionally_notifies(ntfy_env, monkeypatch):
    async def _boom(_cfg):
        raise audi.AudiError("login failed")

    monkeypatch.setattr(main, "fetch_battery", _boom)
    sent = []
    monkeypatch.setattr(main.notify, "send", lambda cfg, title, msg: sent.append((title, msg)))

    # Default: do not notify on error.
    assert main.run([]) == 1
    assert sent == []

    # With NOTIFY_ON_ERROR enabled, an error push is sent.
    monkeypatch.setenv("NOTIFY_ON_ERROR", "true")
    assert main.run([]) == 1
    assert len(sent) == 1


def test_test_notify_flag(ntfy_env, monkeypatch):
    sent = []
    monkeypatch.setattr(main.notify, "send", lambda cfg, title, msg: sent.append((title, msg)))
    # fetch_battery must NOT be called for --test-notify.
    monkeypatch.setattr(main, "fetch_battery", _async_return(None))

    assert main.run(["--test-notify"]) == 0
    assert len(sent) == 1


# --- notifier dispatch -----------------------------------------------------------------

class _FakeResponse:
    def raise_for_status(self):
        pass


def test_notify_ntfy_posts_to_topic_url(ntfy_env, monkeypatch):
    cfg = load_config()
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return _FakeResponse()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    notify.send(cfg, "Title", "Body")

    assert calls["url"] == "https://ntfy.sh/topic-123"
    assert calls["kwargs"]["data"] == b"Body"
    assert calls["kwargs"]["headers"]["Title"] == "Title"


def test_notify_pushover_posts_to_api(monkeypatch):
    monkeypatch.setenv("AUDI_USERNAME", "me@example.com")
    monkeypatch.setenv("AUDI_PASSWORD", "secret")
    monkeypatch.setenv("AUDI_COUNTRY", "GB")
    monkeypatch.setenv("NOTIFY_BACKEND", "pushover")
    monkeypatch.setenv("PUSHOVER_TOKEN", "tok")
    monkeypatch.setenv("PUSHOVER_USER", "usr")
    cfg = load_config()
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["data"] = kwargs["data"]
        return _FakeResponse()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    notify.send(cfg, "Title", "Body")

    assert calls["url"] == "https://api.pushover.net/1/messages.json"
    assert calls["data"]["token"] == "tok"
    assert calls["data"]["user"] == "usr"


def test_notify_telegram_posts_to_api(monkeypatch):
    monkeypatch.setenv("AUDI_USERNAME", "me@example.com")
    monkeypatch.setenv("AUDI_PASSWORD", "secret")
    monkeypatch.setenv("AUDI_COUNTRY", "GB")
    monkeypatch.setenv("NOTIFY_BACKEND", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "botABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    cfg = load_config()
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["data"] = kwargs["data"]
        return _FakeResponse()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    notify.send(cfg, "Title", "Body")

    assert calls["url"] == "https://api.telegram.org/botbotABC/sendMessage"
    assert calls["data"]["chat_id"] == "999"
    assert "Title" in calls["data"]["text"]


# --- SoC detection ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"state_of_charge": 73}, 73),
        ({"battery": {"stateOfCharge": 21.4}}, 21),
        ({"charging": {"battery_status": {"current_soc_pct": 55}}}, 55),
        ({"batteryLevel": "88%"}, 88),
        ({"some": {"deep": {"socPct": 12}}}, 12),
    ],
)
def test_extract_soc_finds_percentage(raw, expected):
    assert audi._extract_soc(raw) == expected


def test_extract_soc_ignores_unrelated_and_out_of_range():
    # "associated" contains the substring "soc" but must not be treated as SoC; mileage is >100.
    raw = {"associated_user": "bob", "mileage": 45213, "charging_state": "off"}
    assert audi._extract_soc(raw) is None


def test_extract_soc_prefers_explicit_soc_over_weaker_match():
    raw = {"charge_level": 99, "state_of_charge": 42}
    assert audi._extract_soc(raw) == 42


def test_find_vin_from_nested_data():
    raw = {"vehicle": {"vin": "WAUZZZ999"}}
    assert audi._find_vin(raw) == "WAUZZZ999"
