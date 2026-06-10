"""Connect to the myAudi cloud and read the battery state of charge.

Uses the vendored Audi client (see ev_charge/vendor/audiconnect/), which is the API layer
extracted from the actively maintained Home Assistant `audi_connect_ha` integration. The exact
battery attribute can still vary, so we read the client's `state_of_charge` property and fall back
to searching the vehicle object for a state-of-charge field. This fails loudly (BatteryReadError)
rather than reporting wrong data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config


class AudiError(Exception):
    """Raised when we cannot log in or find the requested vehicle."""


class BatteryReadError(AudiError):
    """Raised when the vehicle was found but no battery percentage could be located."""


@dataclass
class BatteryReading:
    soc: int
    vin: str
    raw: dict  # plain-data snapshot of the vehicle, for --dump / debugging


def _install_ha_shim() -> None:
    """Satisfy the handful of ``homeassistant.const`` names the vendored ``const.py`` imports,
    so the client runs standalone without installing Home Assistant. Idempotent and harmless if
    Home Assistant *is* installed (we don't overwrite a real module).
    """
    import sys
    import types

    if "homeassistant.const" in sys.modules or "homeassistant" in sys.modules:
        return

    class _PlatformMeta(type):
        # const.py builds PLATFORMS = [Platform.SENSOR, ...]; any member name resolves to a string.
        def __getattr__(cls, name):
            return name.lower()

    class Platform(metaclass=_PlatformMeta):
        pass

    ha = types.ModuleType("homeassistant")
    const = types.ModuleType("homeassistant.const")
    const.CONF_PASSWORD = "password"
    const.CONF_USERNAME = "username"
    const.Platform = Platform
    ha.const = const
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = const


async def fetch_battery(cfg: Config) -> BatteryReading:
    """Log in to myAudi, locate the target vehicle, and return its battery reading."""
    import aiohttp

    _install_ha_shim()
    try:
        from .vendor.audiconnect.audi_connect_account import AudiConnectAccount
    except ImportError as exc:
        raise AudiError(
            f"Could not import the vendored Audi client ({exc}). Make sure the six .py files are "
            "present under ev_charge/vendor/audiconnect/ — see its README.md."
        ) from exc

    async with aiohttp.ClientSession() as session:
        account = AudiConnectAccount(
            session, cfg.username, cfg.password, cfg.country, cfg.spin, cfg.api_level
        )
        try:
            await account.login()
            await account.update(None)
        except Exception as exc:  # noqa: BLE001 - surface any login/fetch failure uniformly
            raise AudiError(f"myAudi login/update failed: {exc}") from exc

        vehicles = list(getattr(account, "vehicles", None) or [])
        if not vehicles:
            raise AudiError("No vehicles found on this myAudi account")

        vehicle = _select_vehicle(vehicles, cfg.vin)
        raw = _to_plain(vehicle)
        vin = (getattr(vehicle, "vin", None) or _find_vin(raw) or cfg.vin or "unknown")
        if isinstance(vin, str):
            vin = vin.strip()

        soc = _vehicle_soc(vehicle)
        if soc is None:
            soc = _extract_soc(raw)  # fallback: scan the vehicle object
        if soc is None:
            raise BatteryReadError(
                "Could not find a battery state-of-charge value for the vehicle. "
                "Run with --dump to inspect the available data."
            )
        return BatteryReading(soc=soc, vin=str(vin), raw=raw)


def _select_vehicle(vehicles: list, vin: str | None):
    if not vin:
        return vehicles[0]
    target = vin.strip().upper()
    for v in vehicles:
        found = getattr(v, "vin", None) or _find_vin(_to_plain(v))
        if isinstance(found, str) and found.strip().upper() == target:
            return v
    raise AudiError(f"VIN {vin} not found among {len(vehicles)} vehicle(s) on the account")


def _vehicle_soc(vehicle) -> int | None:
    """Read the client's own state-of-charge property, if it exposes one."""
    if not getattr(vehicle, "state_of_charge_supported", True):
        return None
    try:
        return _as_percentage(getattr(vehicle, "state_of_charge", None))
    except Exception:  # noqa: BLE001 - property access can raise on partial data
        return None


def _find_vin(raw: dict) -> str | None:
    for key, value in _walk(raw):
        if isinstance(value, str) and "vin" in _tokens(key) and value.strip():
            return value.strip()
    return None


# --- state-of-charge detection (fallback) ----------------------------------------------

def _extract_soc(raw: dict) -> int | None:
    """Search the plain vehicle data for the most likely battery percentage."""
    best_score = -1
    best_value: int | None = None
    for key, value in _walk(raw):
        score = _soc_key_score(_tokens(key))
        if score < 0:
            continue
        number = _as_percentage(value)
        if number is None:
            continue
        if score > best_score:
            best_score = score
            best_value = number
    return best_value


def _soc_key_score(tokens: list[str]) -> int:
    """Higher score = more confident this key is the battery state of charge. -1 = not a match."""
    token_set = set(tokens)
    joined = "".join(tokens)
    if any(t == "soc" or t.startswith("soc") for t in tokens) or "stateofcharge" in joined:
        return 3
    if "battery" in token_set and (token_set & {"level", "percent", "pct"} or "soc" in joined):
        return 2
    if "charge" in token_set and (token_set & {"level", "percent", "pct"}) and "charging" not in token_set:
        return 1
    return -1


def _as_percentage(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().rstrip("%").strip())
        except ValueError:
            return None
    else:
        return None
    if 0 <= number <= 100:
        return int(round(number))
    return None


def _tokens(key) -> list[str]:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return [t.lower() for t in text.split()]


# --- object -> plain data --------------------------------------------------------------

def _to_plain(obj, depth: int = 0, _seen: set[int] | None = None):
    """Convert an arbitrary object graph into dicts/lists/scalars (depth- and cycle-limited)."""
    _seen = _seen if _seen is not None else set()
    if depth > 6 or obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if id(obj) in _seen:
        return None
    _seen.add(id(obj))

    if isinstance(obj, dict):
        return {str(k): _to_plain(v, depth + 1, _seen) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_plain(v, depth + 1, _seen) for v in obj]

    attrs = getattr(obj, "__dict__", None)
    if attrs:
        return {
            str(k): _to_plain(v, depth + 1, _seen)
            for k, v in attrs.items()
            if not str(k).startswith("_") or str(k) in ("_vehicle", "_vin")
        }
    return repr(obj)


def _walk(data, prefix: str = ""):
    """Yield (key, value) for every scalar leaf in a nested dict/list structure."""
    if isinstance(data, dict):
        for key, value in data.items():
            yield from _walk(value, key)
    elif isinstance(data, list):
        for item in data:
            yield from _walk(item, prefix)
    else:
        yield prefix, data
