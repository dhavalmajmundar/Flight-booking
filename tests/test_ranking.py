from datetime import date, datetime

from flight_bot.models import Cabin, FlightOption, Leg, Priority, SearchRequest
from flight_bot.ranking import rank_flights


def option(identifier: str, price: float, minutes: int, stops: int) -> FlightOption:
    return FlightOption(
        offer_id=identifier,
        airlines=("Test Air",),
        airline_codes=("TA",),
        legs=(
            Leg(
                origin="JFK",
                destination="LAX",
                departure=datetime(2026, 9, 15, 8),
                arrival=datetime(2026, 9, 15, 12),
                duration_minutes=minutes,
                stops=stops,
            ),
        ),
        total_price=price,
        currency="USD",
        checked_bags=1,
    )


def request(priority: Priority = Priority.BALANCED) -> SearchRequest:
    return SearchRequest(
        origin="JFK",
        destination="LAX",
        departure_date=date(2026, 9, 15),
        return_date=None,
        adults=1,
        cabin=Cabin.ECONOMY,
        flexible_dates=False,
        nearby_airports=False,
        checked_bags=0,
        priority=priority,
    )


def test_special_categories_are_correct() -> None:
    cheap = option("cheap", 150, 420, 1)
    fast = option("fast", 260, 300, 0)
    middle = option("middle", 190, 330, 0)
    result = rank_flights([cheap, fast, middle], request())
    assert result is not None
    assert result.cheapest is cheap
    assert result.fastest is fast


def test_cheapest_priority_favors_price() -> None:
    cheap = option("cheap", 100, 360, 1)
    expensive = option("expensive", 300, 300, 0)
    result = rank_flights([cheap, expensive], request(Priority.CHEAPEST))
    assert result is not None
    assert result.best_overall is cheap


def test_cheapest_travel_date_uses_daily_lowest_fares() -> None:
    requested = option("requested", 300, 300, 0)
    earlier = option("earlier", 180, 330, 0)
    earlier.legs = (
        Leg(
            origin="JFK",
            destination="LAX",
            departure=datetime(2026, 9, 14, 8),
            arrival=datetime(2026, 9, 14, 13, 30),
            duration_minutes=330,
            stops=0,
        ),
    )
    result = rank_flights([requested, earlier], request())
    assert result is not None
    assert result.cheapest_travel_date is earlier
    assert [travel_date for travel_date, _ in result.lowest_by_date] == [
        date(2026, 9, 14),
        date(2026, 9, 15),
    ]
