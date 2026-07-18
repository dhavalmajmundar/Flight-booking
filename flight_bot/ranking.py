from __future__ import annotations

from dataclasses import dataclass

from .models import FlightOption, Priority, SearchRequest


@dataclass(frozen=True)
class RankedResults:
    ordered: list[FlightOption]
    best_overall: FlightOption
    cheapest: FlightOption
    fastest: FlightOption
    best_flexible: FlightOption | None


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return (value - low) / (high - low)


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
        if offer.stops >= 2:
            offer.warnings.append("Multiple connections increase disruption risk")
        for leg in offer.legs:
            for airport, minutes in leg.layovers:
                if minutes < 50:
                    offer.warnings.append(
                        f"Tight {minutes}-minute connection at {airport}"
                    )
                elif minutes > 240:
                    offer.warnings.append(
                        f"Long {minutes // 60}h {minutes % 60:02d}m layover at {airport}"
                    )
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
    return RankedResults(
        ordered=ordered,
        best_overall=ordered[0],
        cheapest=cheapest,
        fastest=fastest,
        best_flexible=best_flexible,
    )
