from __future__ import annotations

from html import escape

from .models import FlightOption, SearchRequest
from .ranking import RankedResults, observed_deal_label


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


def _flexible_date_lines(
    results: RankedResults, request: SearchRequest
) -> list[str]:
    if not request.flexible_dates or not results.lowest_by_date:
        return []

    cheapest = results.cheapest_travel_date
    cheapest_date = cheapest.legs[0].departure.date()
    requested_option = dict(results.lowest_by_date).get(request.departure_date)
    lines = ["📅 <b>Cheapest travel-day check (±3 days)</b>"]
    for travel_date, option in results.lowest_by_date:
        marker = " 🏆" if option is cheapest else ""
        lines.append(
            f"{travel_date:%a %b %d}: {option.currency} "
            f"{option.total_price:,.2f}{marker}"
        )
    lines.append(
        f"<b>Best day:</b> {cheapest_date:%A, %B %d} — "
        f"{cheapest.currency} {cheapest.total_price:,.2f}"
    )
    if requested_option:
        savings = requested_option.total_price - cheapest.total_price
        day_difference = (cheapest_date - request.departure_date).days
        if savings > 0.005:
            direction = (
                f"{abs(day_difference)} day(s) "
                f"{'later' if day_difference > 0 else 'earlier'}"
            )
            lines.append(
                f"<b>Potential saving:</b> {cheapest.currency} {savings:,.2f} "
                f"by departing {direction}."
            )
        else:
            lines.append("Your requested departure date is already the cheapest found.")
    else:
        lines.append("No matching fare was returned for the requested departure date.")
    lines.extend(
        [
            "These are live fares for travel dates, not a prediction about which "
            "weekday to purchase.",
            "",
        ]
    )
    return lines


def selected_results(results: RankedResults, limit: int = 5) -> list[FlightOption]:
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
        if len(selected) >= limit:
            break
    return selected


def format_results(
    results: RankedResults,
    request: SearchRequest,
    origin_label: str,
    destination_label: str,
    observed_prices: list[float] | None = None,
    search_note: str | None = None,
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

    selected = selected_results(results)

    lines = [
        "✈️ <b>Live flight comparison</b>",
        f"{escape(origin_label)} → {escape(destination_label)}",
        f"Prices are total for {request.adults} adult(s), including provider-reported taxes/fees.",
        "",
    ]
    if search_note:
        lines.extend([f"🔎 <b>Search strategy:</b> {escape(search_note)}", ""])
    lines.extend(_flexible_date_lines(results, request))
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
        carry_on = (
            f"{option.carry_on_bags} carry-on bag(s) shown included"
            if option.carry_on_bags is not None
            else "carry-on allowance not clearly reported"
        )
        lines.extend(
            [
                f"<b>Baggage:</b> {baggage}; {carry_on}",
                f"<b>Total:</b> {option.currency} {option.total_price:,.2f}",
                f"<b>Source:</b> {option.source} live API",
                f"<b>Why:</b> {_reason(option, results)}",
            ]
        )
        if observed_prices is not None:
            lines.append(
                f"<b>Observed deal level:</b> "
                f"{escape(observed_deal_label(option.total_price, observed_prices))}"
            )
        if option.warnings:
            warnings = list(dict.fromkeys(option.warnings))
            major = [item for item in warnings if item.startswith("HIGH RISK:")]
            other = [item for item in warnings if item not in major]
            if major:
                lines.append(
                    "🚨 <b>Important itinerary warning:</b> "
                    f"{escape('; '.join(major))}"
                )
            if other:
                lines.append(f"⚠️ {escape('; '.join(other))}")
        lines.append("")

    lines.extend(
        [
            "<b>Recommendation</b>",
            "Book #1 for the best overall balance. Choose the option tagged Cheapest "
            "only if its timing, connections, and baggage terms work for you; choose "
            "Fastest when reduced travel time is worth any fare difference.",
            "",
            "Fares can change until ticketed. RouteStack is the search source; "
            "the bot revalidates an itinerary before opening RouteStack's hosted "
            "checkout. The bot does not take payment or issue tickets. "
            "Change/cancellation terms and exact bag fees must be verified at checkout.",
        ]
    )
    return "\n".join(lines)
