from __future__ import annotations

from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
import re
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


def _distance_km(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    lat1, lon1, lat2, lon2 = map(
        radians, (first[0], first[1], second[0], second[1])
    )
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(value))


def local_airport_suggestions(
    query: str, limit: int = 5
) -> list[tuple[str, str, str]]:
    """Find likely airports for a city/state locally, without a provider call."""
    exact = local_airport(query)
    if exact:
        return [exact]
    parts = [part.strip() for part in query.split(",") if part.strip()]
    city = parts[0].casefold() if parts else query.strip().casefold()
    region = parts[1].casefold() if len(parts) > 1 else ""
    region_aliases = {
        "al": "alabama",
        "ak": "alaska",
        "az": "arizona",
        "ar": "arkansas",
        "co": "colorado",
        "ct": "connecticut",
        "de": "delaware",
        "ny": "new york",
        "nj": "new jersey",
        "ca": "california",
        "tx": "texas",
        "fl": "florida",
        "il": "illinois",
        "ma": "massachusetts",
        "ga": "georgia",
        "wa": "washington",
        "dc": "district of columbia",
        "hi": "hawaii",
        "id": "idaho",
        "in": "indiana",
        "ia": "iowa",
        "ks": "kansas",
        "ky": "kentucky",
        "la": "louisiana",
        "me": "maine",
        "md": "maryland",
        "mi": "michigan",
        "mn": "minnesota",
        "ms": "mississippi",
        "mo": "missouri",
        "mt": "montana",
        "ne": "nebraska",
        "nv": "nevada",
        "nh": "new hampshire",
        "nm": "new mexico",
        "nc": "north carolina",
        "nd": "north dakota",
        "oh": "ohio",
        "ok": "oklahoma",
        "or": "oregon",
        "pa": "pennsylvania",
        "ri": "rhode island",
        "sc": "south carolina",
        "sd": "south dakota",
        "tn": "tennessee",
        "ut": "utah",
        "vt": "vermont",
        "va": "virginia",
        "wv": "west virginia",
        "wi": "wisconsin",
        "wy": "wyoming",
        "ab": "alberta",
        "on": "ontario",
        "qc": "quebec",
        "bc": "british columbia",
        "mb": "manitoba",
        "nb": "new brunswick",
        "nl": "newfoundland and labrador",
        "ns": "nova scotia",
        "nt": "northwest territories",
        "nu": "nunavut",
        "pe": "prince edward island",
        "sk": "saskatchewan",
        "yt": "yukon",
    }
    region = region_aliases.get(region, region)
    common_metros = {
        "new york": ("JFK", "LGA", "EWR"),
        "los angeles": ("LAX", "BUR", "LGB", "SNA", "ONT"),
        "london": ("LHR", "LGW", "LCY", "STN", "LTN"),
        "toronto": ("YYZ", "YTZ", "YHM"),
        "chicago": ("ORD", "MDW"),
        "washington": ("DCA", "IAD", "BWI"),
        "san francisco": ("SFO", "OAK", "SJC"),
        "dallas": ("DFW", "DAL"),
        "houston": ("IAH", "HOU"),
        "miami": ("MIA", "FLL", "PBI"),
    }
    metro_regions = {
        "new york": {"", "new york", "us", "usa"},
        "los angeles": {"", "california", "us", "usa"},
        "london": {"", "england", "gb", "uk", "united kingdom"},
        "toronto": {"", "ontario", "canada"},
        "chicago": {"", "illinois", "us", "usa"},
        "washington": {"", "district of columbia", "us", "usa"},
        "san francisco": {"", "california", "us", "usa"},
        "dallas": {"", "texas", "us", "usa"},
        "houston": {"", "texas", "us", "usa"},
        "miami": {"", "florida", "us", "usa"},
    }
    if city in common_metros and region in metro_regions[city]:
        results: list[tuple[str, str, str]] = []
        for code in common_metros[city][:limit]:
            airport = _iata_airports().get(code)
            if not airport:
                continue
            name = str(airport.get("name") or code)
            airport_city = str(airport.get("city") or "").strip()
            subdivision = str(airport.get("subd") or "").strip()
            results.append(
                (
                    code,
                    f"[{code}] {name}, {airport_city}, {subdivision}".rstrip(", "),
                    str(airport.get("country") or "").upper(),
                )
            )
        return results
    matches: list[tuple[str, dict[str, Any]]] = []
    for code, airport in _iata_airports().items():
        airport_city = str(airport.get("city") or "").strip().casefold()
        subdivision = str(airport.get("subd") or "").strip().casefold()
        if airport_city != city:
            continue
        if region and region not in {
            subdivision,
            str(airport.get("country") or "").strip().casefold(),
        }:
            continue
        matches.append((code, airport))
    if not matches and len(city) >= 3:
        for code, airport in _iata_airports().items():
            haystack = " ".join(
                str(airport.get(key) or "") for key in ("city", "name", "subd")
            ).casefold()
            if re.search(rf"\b{re.escape(city)}\b", haystack):
                matches.append((code, airport))
    if not matches:
        return []

    center = (
        sum(float(item.get("lat") or 0) for _, item in matches) / len(matches),
        sum(float(item.get("lon") or 0) for _, item in matches) / len(matches),
    )
    country = str(matches[0][1].get("country") or "")
    nearby: list[tuple[float, str, dict[str, Any]]] = []
    for code, airport in _iata_airports().items():
        if str(airport.get("country") or "") != country:
            continue
        distance = _distance_km(
            center,
            (float(airport.get("lat") or 0), float(airport.get("lon") or 0)),
        )
        if distance <= 80:
            nearby.append((distance, code, airport))
    nearby.sort(
        key=lambda item: (
            "international" not in str(item[2].get("name") or "").casefold(),
            item[0],
        )
    )
    results: list[tuple[str, str, str]] = []
    for _, code, airport in nearby:
        name = str(airport.get("name") or code)
        airport_city = str(airport.get("city") or "").strip()
        subdivision = str(airport.get("subd") or "").strip()
        label = f"[{code}] {name}, {airport_city}, {subdivision}".rstrip(", ")
        value = (code, label, str(airport.get("country") or "").upper())
        if value not in results:
            results.append(value)
        if len(results) >= limit:
            break
    return results


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
