from __future__ import annotations

from functools import lru_cache
from typing import Any

import airportsdata


@lru_cache(maxsize=1)
def _iata_airports() -> dict[str, dict[str, Any]]:
    return airportsdata.load("IATA")


def local_airport(query: str) -> tuple[str, str, str] | None:
    """Resolve an exact IATA airport code without making a provider call."""
    code = query.strip().upper()
    if len(code) != 3 or not code.isalpha():
        return None
    airport = _iata_airports().get(code)
    if not airport:
        return None
    name = str(airport.get("name") or code)
    city = str(airport.get("city") or "").strip()
    country = str(airport.get("country") or "").strip().upper()
    place = ", ".join(part for part in (city, country) if part)
    label = f"[{code}] {name}" + (f", {place}" if place else "")
    return code, label, country


def smart_baggage(origin_country: str, destination_country: str) -> tuple[int, int]:
    """Return checked and carry-on defaults; unknown routes use the safer allowance."""
    domestic = is_domestic(origin_country, destination_country)
    return (0 if domestic else 2), 1


def is_domestic(origin_country: str, destination_country: str) -> bool:
    return bool(
        origin_country
        and destination_country
        and origin_country == destination_country
    )
