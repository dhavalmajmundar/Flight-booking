from datetime import date, datetime

from flight_bot.models import Cabin, DepartureWindow, FlightOption, Leg, Priority, SearchRequest
from flight_bot.ranking import (
    has_major_itinerary_risk,
    observed_deal_label,
    rank_flights,
)


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


def test_comfort_preferences_warn_and_penalize_without_filtering() -> None:
    red_eye = option("red", 100, 500, 2)
    red_eye.legs = (
        Leg("JFK", "LAX", datetime(2026, 9, 15, 23), datetime(2026, 9, 16, 5), 500, 2),
    )
    normal = option("normal", 130, 360, 0)
    search = request()
    search.departure_window = DepartureWindow.MORNING
    search.max_stops = 1
    search.avoid_red_eye = True
    result = rank_flights([red_eye, normal], search)
    assert result is not None
    assert red_eye in result.ordered
    assert any("Red-eye" in warning for warning in red_eye.warnings)
    assert any("maximum" in warning for warning in red_eye.warnings)


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


def test_unsafe_itinerary_is_kept_highlighted_and_penalized() -> None:
    risky = option("risky", 100, 300, 1)
    risky.self_transfer = True
    safe = option("safe", 120, 310, 0)
    result = rank_flights([risky, safe], request())
    assert result is not None
    assert risky in result.ordered
    assert has_major_itinerary_risk(risky)
    assert any("HIGH RISK" in warning for warning in risky.warnings)
    assert result.best_overall is safe


def test_observed_deal_label_never_claims_market_history() -> None:
    assert "Building route history" in observed_deal_label(400, [450])
    assert "Excellent" in observed_deal_label(390, [400, 450, 500])
    assert "Expensive" in observed_deal_label(600, [400, 450, 500])
