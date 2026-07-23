from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import DepartureWindow, FlightOption, Priority, SearchRequest


@dataclass(frozen=True)
class RankedResults:
    ordered: list[FlightOption]
    best_overall: FlightOption
    cheapest: FlightOption
    fastest: FlightOption
    best_flexible: FlightOption | None
    lowest_by_date: tuple[tuple[date, FlightOption], ...]
    cheapest_travel_date: FlightOption


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return (value - low) / (high - low)


def itinerary_risks(option: FlightOption) -> list[str]:
    """Return material itinerary drawbacks without excluding the fare."""
    risks: list[str] = []
    if option.self_transfer:
        risks.append("HIGH RISK: self-transfer or separate-ticket connection reported")
    if option.stops >= 2:
        risks.append("Multiple connections increase disruption risk")
    for leg in option.legs:
        if leg.airport_changes:
            for arrival_airport, departure_airport, minutes in leg.airport_changes:
                risks.append(
                    "HIGH RISK: connection changes airports "
                    f"{arrival_airport} → {departure_airport} in "
                    f"{minutes // 60}h {minutes % 60:02d}m"
                )
        for airport in leg.overnight_layovers:
            risks.append(f"Overnight connection at {airport}")
        for airport, minutes in leg.layovers:
            if minutes < 60:
                risks.append(
                    f"HIGH RISK: tight {minutes}-minute connection at {airport}"
                )
            elif minutes > 300:
                risks.append(
                    f"Long {minutes // 60}h {minutes % 60:02d}m layover at {airport}"
                )
        if leg.duration_minutes > 18 * 60:
            risks.append(
                f"Very long {leg.duration_minutes // 60}h "
                f"{leg.duration_minutes % 60:02d}m travel leg"
            )
    return list(dict.fromkeys(risks))


def has_major_itinerary_risk(option: FlightOption) -> bool:
    return any(
        warning.startswith("HIGH RISK:") for warning in itinerary_risks(option)
    )


def observed_deal_label(
    price: float, observed_prices: list[float]
) -> str:
    """Classify a fare only against prices previously observed by this bot."""
    history = [value for value in observed_prices if value > 0]
    if len(history) < 3:
        return f"Building route history ({len(history)} prior observation(s))"
    ordered = sorted(history)
    median = ordered[len(ordered) // 2]
    record_low = ordered[0]
    if price <= record_low * 1.02:
        return "Excellent — at or near this bot’s observed low"
    if price <= median * 0.95:
        return "Good — at least 5% below this bot’s observed median"
    if price <= median * 1.05:
        return "Typical — near this bot’s observed median"
    return "Expensive — above this bot’s observed range midpoint"


def rank_flights(
    offers: list[FlightOption], request: SearchRequest
) -> RankedResults | None:
    if not offers:
        return None

    prices = [offer.total_price for offer in offers]
    durations = [offer.duration_minutes for offer in offers]
    min_price, max_price = min(prices), max(prices)
    min_duration, max_duration = min(durations), max(durations)

    weights = {
        Priority.BALANCED: (0.48, 0.27, 0.18),
        Priority.CHEAPEST: (0.72, 0.15, 0.08),
        Priority.FASTEST: (0.20, 0.62, 0.12),
        Priority.NONSTOP: (0.25, 0.18, 0.50),
    }
    price_weight, duration_weight, stop_weight = weights[request.priority]

    for offer in offers:
        score = (
            price_weight * _normalize(offer.total_price, min_price, max_price)
            + duration_weight
            * _normalize(offer.duration_minutes, min_duration, max_duration)
            + stop_weight * min(offer.stops, 3) / 3
        )
        if request.preferred_airlines.intersection(offer.airline_codes):
            score -= 0.08
        if request.max_budget is not None and offer.total_price > request.max_budget:
            score += 0.50
            offer.warnings.append(
                f"Exceeds your total budget by {offer.currency} "
                f"{offer.total_price - request.max_budget:,.2f}"
            )
        max_leg_stops = max(leg.stops for leg in offer.legs)
        if request.max_stops is not None and max_leg_stops > request.max_stops:
            score += 0.30 * (max_leg_stops - request.max_stops)
            offer.warnings.append(
                f"A direction exceeds your maximum of {request.max_stops} stop(s)"
            )
        if (
            request.max_total_duration_minutes is not None
            and any(
                leg.duration_minutes > request.max_total_duration_minutes
                for leg in offer.legs
            )
        ):
            score += 0.20
            offer.warnings.append(
                "A direction exceeds your preferred travel time of "
                f"{request.max_total_duration_minutes // 60}h"
            )
        first_hour = offer.legs[0].departure.hour
        windows = {
            DepartureWindow.MORNING: range(5, 12),
            DepartureWindow.AFTERNOON: range(12, 17),
            DepartureWindow.EVENING: range(17, 22),
        }
        if request.departure_window in windows and first_hour not in windows[request.departure_window]:
            score += 0.12
            offer.warnings.append(
                f"Departure is outside your {request.departure_window.value} preference"
            )
        is_red_eye = first_hour >= 22 or first_hour < 5 or any(
            leg.arrival.hour < 6 for leg in offer.legs
        )
        if request.avoid_red_eye and is_red_eye:
            score += 0.18
            offer.warnings.append("Red-eye or overnight arrival conflicts with your preference")
        if request.checked_bags > 0:
            if offer.checked_bags is None:
                score += 0.08
                offer.warnings.append("Checked-bag allowance not clearly reported")
            elif offer.checked_bags < request.checked_bags:
                score += 0.18
                offer.warnings.append(
                    f"Only {offer.checked_bags} checked bag(s) shown as included"
                )
        if request.carry_on_bags > 0:
            if offer.carry_on_bags is None:
                offer.warnings.append("Carry-on allowance not clearly reported")
            elif offer.carry_on_bags < request.carry_on_bags:
                score += 0.08
                offer.warnings.append(
                    f"Only {offer.carry_on_bags} carry-on bag(s) shown as included"
                )
        risks = itinerary_risks(offer)
        for leg in offer.legs:
            for airport, minutes in leg.layovers:
                if minutes < request.min_layover_minutes:
                    risks.append(
                        f"Connection at {airport} is below your "
                        f"{request.min_layover_minutes}-minute minimum"
                    )
                if (
                    minutes > request.max_layover_minutes
                    and not any(
                        airport in warning and "layover" in warning.lower()
                        for warning in risks
                    )
                ):
                    risks.append(
                        f"Layover at {airport} exceeds your "
                        f"{request.max_layover_minutes // 60}h "
                        f"{request.max_layover_minutes % 60:02d}m preference"
                    )
        offer.warnings.extend(risks)
        for risk in risks:
            if risk.startswith("HIGH RISK:"):
                score += 0.75
            elif risk.startswith(("Overnight", "Very long", "Multiple")):
                score += 0.12
            elif risk.startswith("Long"):
                score += 0.07
        offer.score = score

    ordered = sorted(offers, key=lambda item: (item.score, item.total_price))
    cheapest = min(offers, key=lambda item: (item.total_price, item.duration_minutes))
    fastest = min(offers, key=lambda item: (item.duration_minutes, item.total_price))
    best_flexible = None
    if request.flexible_dates:
        off_date = [
            offer
            for offer in offers
            if offer.legs[0].departure.date() != request.departure_date
        ]
        if off_date:
            best_flexible = min(
                off_date, key=lambda item: (item.total_price, item.duration_minutes)
            )
    by_date: dict[date, FlightOption] = {}
    for offer in offers:
        departure_date = offer.legs[0].departure.date()
        current = by_date.get(departure_date)
        if current is None or (
            offer.total_price,
            offer.duration_minutes,
        ) < (
            current.total_price,
            current.duration_minutes,
        ):
            by_date[departure_date] = offer
    lowest_by_date = tuple(sorted(by_date.items()))
    cheapest_travel_date = min(
        by_date.values(),
        key=lambda item: (item.total_price, item.duration_minutes),
    )
    return RankedResults(
        ordered=ordered,
        best_overall=ordered[0],
        cheapest=cheapest,
        fastest=fastest,
        best_flexible=best_flexible,
        lowest_by_date=lowest_by_date,
        cheapest_travel_date=cheapest_travel_date,
    )
