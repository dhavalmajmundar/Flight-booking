from datetime import date, datetime

from flight_bot.formatting import format_results, selected_results
from flight_bot.models import Cabin, FlightOption, Leg, SearchRequest
from flight_bot.ranking import rank_flights


def option(identifier: str, price: float, minutes: int) -> FlightOption:
    return FlightOption(
        offer_id=identifier,
        airlines=("Test Air",),
        airline_codes=("TA",),
        legs=(
            Leg(
                origin="JFK",
                destination="LAX",
                departure=datetime(2026, 11, 6, 8),
                arrival=datetime(2026, 11, 6, 11),
                duration_minutes=minutes,
                stops=0,
            ),
        ),
        total_price=price,
        currency="USD",
        checked_bags=1,
        booking_payload={"id": identifier},
    )


def request() -> SearchRequest:
    return SearchRequest(
        origin="JFK",
        destination="LAX",
        departure_date=date(2026, 11, 6),
        return_date=None,
        adults=1,
        cabin=Cabin.ECONOMY,
        flexible_dates=False,
        nearby_airports=False,
        checked_bags=0,
    )


def test_results_include_three_distinct_recommendations_and_safety_notice() -> None:
    results = rank_flights(
        [
            option("cheap", 100, 400),
            option("fast", 250, 180),
            option("balanced", 160, 240),
        ],
        request(),
    )
    assert results is not None
    selected = selected_results(results, limit=3)
    assert len(selected) == 3
    assert len({item.offer_id for item in selected}) == 3

    message = format_results(results, request(), "New York", "Los Angeles")
    assert "Best overall" in message
    assert "Cheapest" in message
    assert "Fastest" in message
    assert "does not take payment or issue tickets" in message
