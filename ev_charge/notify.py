"""Push-notification delivery. Dispatches on the configured backend."""

from __future__ import annotations

import requests

from .config import Config

# A push provider should respond quickly; cron will surface anything slower as a failure.
_TIMEOUT = 15


def send(cfg: Config, title: str, message: str) -> None:
    """Send a push notification via the configured backend. Raises on failure."""
    if cfg.backend == "ntfy":
        _send_ntfy(cfg, title, message)
    elif cfg.backend == "pushover":
        _send_pushover(cfg, title, message)
    elif cfg.backend == "telegram":
        _send_telegram(cfg, title, message)
    else:  # pragma: no cover - config validation prevents this
        raise ValueError(f"Unknown notify backend: {cfg.backend!r}")


def _send_ntfy(cfg: Config, title: str, message: str) -> None:
    resp = requests.post(
        f"{cfg.ntfy_server}/{cfg.ntfy_topic}",
        data=message.encode("utf-8"),
        headers={
            # ntfy reads metadata from headers; Title must be latin-1 safe.
            "Title": title.encode("utf-8").decode("latin-1", "replace"),
            "Priority": "high",
            "Tags": "battery,car",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()


def _send_pushover(cfg: Config, title: str, message: str) -> None:
    resp = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": cfg.pushover_token,
            "user": cfg.pushover_user,
            "title": title,
            "message": message,
            "priority": 1,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()


def _send_telegram(cfg: Config, title: str, message: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
        data={
            "chat_id": cfg.telegram_chat_id,
            "text": f"{title}\n{message}",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
