from __future__ import annotations

from html import escape

from .models import FlightOption, SearchRequest
from .ranking import RankedResults


def minutes_text(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m"


def _option_key(option: FlightOption) -> tuple[str, float]:
    return option.offer_id, option.total_price


def _reason(option: FlightOption, results: RankedResults) -> str:
    reasons = []
    if option is results.best_overall:
        reasons.append("best price/time/convenience balance")
    if option is results.cheapest:
        reasons.append("lowest total fare found")
    if option is results.fastest:
        reasons.append("shortest total travel time")
    if option is results.best_flexible:
        reasons.append("best nearby-date value")
    return "; ".join(reasons) or "strong alternative"


def format_results(
    results: RankedResults,
    request: SearchRequest,
    origin_label: str,
    destination_label: str,
) -> str:
    labels: dict[tuple[str, float], list[str]] = {}
    for label, option in (
        ("Best overall", results.best_overall),
        ("Cheapest", results.cheapest),
        ("Fastest", results.fastest),
        ("Best flexible-date", results.best_flexible),
    ):
        if option:
            labels.setdefault(_option_key(option), []).append(label)

    selected: list[FlightOption] = []
    for option in [
        results.best_overall,
        results.cheapest,
        results.fastest,
        results.best_flexible,
        *results.ordered,
    ]:
        if option and option not in selected:
            selected.append(option)
        if len(selected) >= 5:
            break

    lines = [
        "✈️ <b>Live flight comparison</b>",
        f"{escape(origin_label)} → {escape(destination_label)}",
        f"Prices are total for {request.adults} adult(s), including provider-reported taxes/fees.",
        "",
    ]
    for rank, option in enumerate(selected, 1):
        tags = " · ".join(labels.get(_option_key(option), []))
        if tags:
            lines.append(f"<b>#{rank} — {escape(tags)}</b>")
        else:
            lines.append(f"<b>#{rank}</b>")
        airlines = ", ".join(option.airlines)
        lines.append(f"<b>Airline:</b> {escape(airlines)}")
        for index, leg in enumerate(option.legs):
            direction = "Outbound" if index == 0 else "Return"
            route = f"{leg.origin} → {leg.destination}"
            times = (
                f"{leg.departure:%a %b %d, %H:%M} → "
                f"{leg.arrival:%a %b %d, %H:%M}"
            )
            stop_text = "Nonstop" if leg.stops == 0 else f"{leg.stops} stop(s)"
            lines.append(
                f"<b>{direction}:</b> {route} | {times} | "
                f"{minutes_text(leg.duration_minutes)} | {stop_text}"
            )
            if leg.layovers:
                layover_text = ", ".join(
                    f"{airport} {minutes_text(minutes)}"
                    for airport, minutes in leg.layovers
                )
                lines.append(f"<b>Layover(s):</b> {layover_text}")
        baggage = (
            f"{option.checked_bags} checked bag(s) shown included"
            if option.checked_bags is not None
            else "not clearly reported—verify before payment"
        )
        lines.extend(
            [
                f"<b>Baggage:</b> {baggage}",
                f"<b>Total:</b> {option.currency} {option.total_price:,.2f}",
                f"<b>Source:</b> {option.source} live API",
                f"<b>Why:</b> {_reason(option, results)}",
            ]
        )
        if option.warnings:
            lines.append(f"⚠️ {escape('; '.join(dict.fromkeys(option.warnings)))}")
        lines.append("")

    lines.extend(
        [
            "<b>Recommendation</b>",
            "Book #1 for the best overall balance. Choose the option tagged Cheapest "
            "only if its timing, connections, and baggage terms work for you; choose "
            "Fastest when reduced travel time is worth any fare difference.",
            "",
            "Fares can change until ticketed. RouteStack is the search source; "
            "revalidate the selected itinerary before using its hosted checkout. "
            "Change/cancellation terms and exact bag fees must be verified at checkout.",
        ]
    )
    return "\n".join(lines)
