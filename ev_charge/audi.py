"""Connect to the myAudi cloud and read the battery state of charge.

The exact attribute that holds the battery percentage differs between audiconnectpy
versions and vehicle models, so rather than hard-coding one path we convert the vehicle
object into a plain nested structure and search it for a state-of-charge field. This fails
loudly (BatteryReadError) if nothing plausible is found, instead of silently reporting wrong
data.
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


async def fetch_battery(cfg: Config) -> BatteryReading:
    """Log in to myAudi, locate the target vehicle, and return its battery reading."""
    # Imported lazily so the rest of the package (and the tests) don't require the
    # unofficial library to be installed.
    import aiohttp
    from audiconnectpy import AudiConnect

    async with aiohttp.ClientSession() as session:
        api = AudiConnect(session, cfg.username, cfg.password, cfg.country, cfg.spin)
        try:
            await api.async_update()
        except Exception as exc:  # noqa: BLE001 - surface any login/fetch failure uniformly
            raise AudiError(f"myAudi update failed: {exc}") from exc

        vehicles = list(getattr(api, "vehicles", None) or [])
        if not vehicles:
            raise AudiError("No vehicles found on this myAudi account")

        vehicle = _select_vehicle(vehicles, cfg.vin)
        raw = _to_plain(vehicle)
        vin = _find_vin(vehicle, raw) or (cfg.vin or "unknown")
        soc = _extract_soc(raw)
        if soc is None:
            raise BatteryReadError(
                "Could not find a battery state-of-charge field for the vehicle. "
                "Run with --dump to inspect the available data."
            )
        return BatteryReading(soc=soc, vin=vin, raw=raw)


def _select_vehicle(vehicles: list, vin: str | None):
    if not vin:
        return vehicles[0]
    target = vin.strip().upper()
    for v in vehicles:
        found = _find_vin(v, _to_plain(v))
        if found and found.upper() == target:
            return v
    raise AudiError(f"VIN {vin} not found among {len(vehicles)} vehicle(s) on the account")


def _find_vin(vehicle, raw: dict) -> str | None:
    direct = getattr(vehicle, "vin", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for key, value in _walk(raw):
        if isinstance(value, str) and "vin" in _tokens(key) and value.strip():
            return value.strip()
    return None


# --- state-of-charge detection ---------------------------------------------------------

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
            if not str(k).startswith("_")
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
