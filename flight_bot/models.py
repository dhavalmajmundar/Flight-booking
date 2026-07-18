from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class Cabin(StrEnum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class Priority(StrEnum):
    BALANCED = "balanced"
    CHEAPEST = "cheapest"
    FASTEST = "fastest"
    NONSTOP = "nonstop"


@dataclass
class SearchRequest:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    adults: int
    cabin: Cabin
    flexible_dates: bool
    nearby_airports: bool
    checked_bags: int
    carry_on_bags: int = 1
    auto_baggage: bool = False
    auto_nearby: bool = False
    preferred_airlines: set[str] = field(default_factory=set)
    avoided_airlines: set[str] = field(default_factory=set)
    max_budget: float | None = None
    priority: Priority = Priority.BALANCED
    currency: str = "USD"

    @property
    def round_trip(self) -> bool:
        return self.return_date is not None


@dataclass(frozen=True)
class Leg:
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    duration_minutes: int
    stops: int
    layovers: tuple[tuple[str, int], ...] = ()


@dataclass
class FlightOption:
    offer_id: str
    airlines: tuple[str, ...]
    airline_codes: tuple[str, ...]
    legs: tuple[Leg, ...]
    total_price: float
    currency: str
    checked_bags: int | None
    carry_on_bags: int | None = None
    source: str = "RouteStack"
    bookable_seats: int | None = None
    booking_payload: dict[str, Any] | None = field(default=None, repr=False)
    search_filter: dict[str, Any] | None = field(default=None, repr=False)
    score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_minutes(self) -> int:
        return sum(leg.duration_minutes for leg in self.legs)

    @property
    def stops(self) -> int:
        return sum(leg.stops for leg in self.legs)
