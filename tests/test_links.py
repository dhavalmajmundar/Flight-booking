from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from flight_bot.links import (
    expedia_search_url,
    google_flights_url,
    kayak_search_url,
)
from flight_bot.models import Cabin, FlightOption, Leg, SearchRequest


def test_expedia_round_trip_link_uses_option_dates_and_airline() -> None:
    option = FlightOption(
        offer_id="fare-1",
        airlines=("Test Air",),
        airline_codes=("TA",),
        legs=(
            Leg(
                origin="JFK",
                destination="LAX",
                departure=datetime(2026, 9, 16, 8),
                arrival=datetime(2026, 9, 16, 11),
                duration_minutes=180,
                stops=0,
            ),
            Leg(
                origin="LAX",
                destination="JFK",
                departure=datetime(2026, 9, 23, 12),
                arrival=datetime(2026, 9, 23, 20),
                duration_minutes=300,
                stops=0,
            ),
        ),
        total_price=300,
        currency="USD",
        checked_bags=1,
    )
    request = SearchRequest(
        origin="JFK",
        destination="LAX",
        departure_date=date(2026, 9, 15),
        return_date=date(2026, 9, 22),
        adults=2,
        cabin=Cabin.BUSINESS,
        flexible_dates=True,
        nearby_airports=False,
        checked_bags=0,
    )

    parsed = urlparse(expedia_search_url(option, request))
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/Roundtrip/2026-09-16/2026-09-23")
    assert query["FromAirport"] == ["JFK"]
    assert query["ToAirport"] == ["LAX"]
    assert query["NumAdult"] == ["2"]
    assert query["Class"] == ["2"]
    assert query["Airline"] == ["TA"]
    assert query["Direct"] == ["1"]


def test_expedia_one_way_link_uses_same_end_date() -> None:
    option = FlightOption(
        offer_id="fare-2",
        airlines=("Test Air",),
        airline_codes=("TA",),
        legs=(
            Leg(
                origin="JFK",
                destination="LAX",
                departure=datetime(2026, 9, 16, 8),
                arrival=datetime(2026, 9, 16, 11),
                duration_minutes=180,
                stops=1,
            ),
        ),
        total_price=200,
        currency="USD",
        checked_bags=0,
    )
    request = SearchRequest(
        origin="JFK",
        destination="LAX",
        departure_date=date(2026, 9, 16),
        return_date=None,
        adults=1,
        cabin=Cabin.ECONOMY,
        flexible_dates=False,
        nearby_airports=False,
        checked_bags=0,
    )
    parsed = urlparse(expedia_search_url(option, request))
    assert parsed.path.endswith("/oneway/2026-09-16/2026-09-16")

    google = google_flights_url(option, request)
    kayak = kayak_search_url(option, request)
    assert "google.com/travel/flights" in google
    assert "JFK" in google and "LAX" in google
    assert "/JFK-LAX/2026-09-16/1adult" in kayak
