"""Load and validate configuration from the environment (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional at runtime; env vars still work without it.
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    # Audi
    username: str
    password: str
    country: str
    spin: str | None
    vin: str | None
    api_level: int
    # Alerting
    threshold: int
    backend: str
    notify_on_error: bool
    # Backend params (only the selected backend's values need to be set)
    ntfy_topic: str | None
    ntfy_server: str
    pushover_token: str | None
    pushover_user: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load_config() -> Config:
    """Read configuration, applying defaults and validating the selected notify backend."""
    load_dotenv()  # no-op if there's no .env file

    backend = (os.environ.get("NOTIFY_BACKEND", "ntfy").strip() or "ntfy").lower()

    try:
        threshold = int(os.environ.get("BATTERY_THRESHOLD", "40"))
    except ValueError as exc:
        raise ConfigError("BATTERY_THRESHOLD must be an integer") from exc
    if not 0 <= threshold <= 100:
        raise ConfigError("BATTERY_THRESHOLD must be between 0 and 100")

    try:
        api_level = int(os.environ.get("AUDI_API_LEVEL", "1"))
    except ValueError as exc:
        raise ConfigError("AUDI_API_LEVEL must be an integer (1 for e-tron/Q4)") from exc

    cfg = Config(
        username=_require("AUDI_USERNAME"),
        password=_require("AUDI_PASSWORD"),
        country=_require("AUDI_COUNTRY"),
        spin=_optional("AUDI_SPIN"),
        vin=_optional("AUDI_VIN"),
        api_level=api_level,
        threshold=threshold,
        backend=backend,
        notify_on_error=os.environ.get("NOTIFY_ON_ERROR", "false").strip().lower()
        in ("1", "true", "yes", "on"),
        ntfy_topic=_optional("NTFY_TOPIC"),
        ntfy_server=os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
        or "https://ntfy.sh",
        pushover_token=_optional("PUSHOVER_TOKEN"),
        pushover_user=_optional("PUSHOVER_USER"),
        telegram_bot_token=_optional("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_optional("TELEGRAM_CHAT_ID"),
    )

    _validate_backend(cfg)
    return cfg


def _validate_backend(cfg: Config) -> None:
    if cfg.backend == "ntfy":
        if not cfg.ntfy_topic:
            raise ConfigError("NOTIFY_BACKEND=ntfy requires NTFY_TOPIC")
    elif cfg.backend == "pushover":
        if not (cfg.pushover_token and cfg.pushover_user):
            raise ConfigError(
                "NOTIFY_BACKEND=pushover requires PUSHOVER_TOKEN and PUSHOVER_USER"
            )
    elif cfg.backend == "telegram":
        if not (cfg.telegram_bot_token and cfg.telegram_chat_id):
            raise ConfigError(
                "NOTIFY_BACKEND=telegram requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )
    else:
        raise ConfigError(
            f"Unknown NOTIFY_BACKEND: {cfg.backend!r} (expected ntfy, pushover, or telegram)"
        )
