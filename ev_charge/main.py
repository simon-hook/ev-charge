"""Entry point: read the Audi Q4 battery and alert when it's low."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

from . import notify
from .audi import AudiError, BatteryReading, fetch_battery
from .config import Config, ConfigError, load_config


def _log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the Audi Q4 battery level and send a push alert when it's low."
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Print the raw vehicle data (to locate the battery field) and exit. No alert sent.",
    )
    parser.add_argument(
        "--test-notify",
        action="store_true",
        help="Send a test push via the configured backend and exit. Does not contact the car.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send the low-battery alert regardless of the actual level (end-to-end test).",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        cfg = load_config()
    except ConfigError as exc:
        _log(f"CONFIG ERROR: {exc}")
        return 2

    if args.test_notify:
        notify.send(cfg, "🔋 Audi Q4 monitor test", "If you can read this, notifications work.")
        _log(f"Sent test notification via {cfg.backend}.")
        return 0

    try:
        reading = asyncio.run(fetch_battery(cfg))
    except AudiError as exc:
        _log(f"AUDI ERROR: {exc}")
        if cfg.notify_on_error:
            try:
                notify.send(cfg, "⚠️ Audi Q4 monitor failed", str(exc))
            except Exception as notify_exc:  # noqa: BLE001
                _log(f"Also failed to send error notification: {notify_exc}")
        return 1

    if args.dump:
        print(json.dumps(reading.raw, indent=2, default=str))
        _log(f"Detected battery={reading.soc}% for VIN {reading.vin}.")
        return 0

    _log(f"Q4 {reading.vin} battery={reading.soc}% threshold={cfg.threshold}%")

    if args.force or reading.soc < cfg.threshold:
        _alert(cfg, reading)
        _log("Low-battery alert sent.")
    else:
        _log("Battery above threshold; no alert.")
    return 0


def _alert(cfg: Config, reading: BatteryReading) -> None:
    notify.send(
        cfg,
        "🔋 Audi Q4 low battery",
        f"Battery at {reading.soc}% (below {cfg.threshold}%). Time to plug in.",
    )


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
