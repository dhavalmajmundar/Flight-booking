import asyncio
from datetime import date, datetime

from flight_bot.config import Settings
from flight_bot.models import Cabin, FlightOption, Leg, SearchRequest
from flight_bot.routestack import RouteStackClient


def settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:test",
        routestack_api_key="public-key",
        routestack_api_secret="private-secret",
    )


def test_signed_auth_body_contains_valid_fields() -> None:
    client = RouteStackClient(settings())
    body = client._signed_auth_body()
    assert body["apiKey"] == "public-key"
    assert isinstance(body["timestamp"], int)
    assert body["nonce"]
    assert body["hmac"]


def test_parse_one_way_offer() -> None:
    raw = {
        "fareSourceCode": "fare-1",
        "stops": 1,
        "showOurprice": 215.50,
        "flights": [
            {
                "departure": "JFK",
                "arrival": "ORD",
                "departureTime": "2026-09-15T08:00:00",
                "arrivalTime": "2026-09-15T09:30:00",
                "airline": "Example Air",
                "flightCode": "EA",
            },
            {
                "departure": "ORD",
                "arrival": "LAX",
                "departureTime": "2026-09-15T10:30:00",
                "arrivalTime": "2026-09-15T13:00:00",
                "airline": "Example Air",
                "flightCode": "EA",
            },
        ],
    }
    option = RouteStackClient._parse_offer(
        raw, "USD", 0, "JFK", "LAX", False
    )
    assert option is not None
    assert option.total_price == 215.50
    assert option.legs[0].stops == 1
    assert option.legs[0].layovers == (("ORD", 60),)
    assert option.source == "RouteStack"
    assert option.booking_payload == raw


def test_parse_offer_detects_airport_change_overnight_and_self_transfer() -> None:
    raw = {
        "fareSourceCode": "fare-risky",
        "showOurprice": 150,
        "selfTransfer": True,
        "flights": [
            {
                "departure": "JFK",
                "arrival": "LGA",
                "departureTime": "2026-09-15T20:00:00",
                "arrivalTime": "2026-09-15T22:00:00",
            },
            {
                "departure": "EWR",
                "arrival": "LAX",
                "departureTime": "2026-09-16T08:00:00",
                "arrivalTime": "2026-09-16T11:00:00",
            },
        ],
    }
    option = RouteStackClient._parse_offer(
        raw, "USD", 0, "JFK", "LAX", False
    )
    assert option is not None
    assert option.self_transfer is True
    assert option.legs[0].airport_changes == (("LGA", "EWR", 600),)
    assert option.legs[0].overnight_layovers == ("LGA",)


def test_parse_round_trip_offer() -> None:
    raw = {
        "id": "roundtrip",
        "totalFare": "499.00",
        "flights": [
            {
                "departure": "JFK",
                "arrival": "LAX",
                "departureTime": "2026-09-15T08:00:00",
                "arrivalTime": "2026-09-15T11:00:00",
            },
            {
                "departure": "LAX",
                "arrival": "JFK",
                "departureTime": "2026-09-20T12:00:00",
                "arrivalTime": "2026-09-20T20:00:00",
            },
        ],
    }
    option = RouteStackClient._parse_offer(
        raw, "USD", 0, "JFK", "LAX", True
    )
    assert option is not None
    assert len(option.legs) == 2
    assert option.legs[1].destination == "JFK"


def test_create_checkout_url_revalidates_before_handoff() -> None:
    client = RouteStackClient(settings())
    calls: list[tuple[str, dict]] = []

    async def fake_post(path: str, body: dict) -> dict:
        calls.append((path, body))
        if path.endswith("/revalidate"):
            return {"revalidate": {"fresh": True}}
        return {"success": True, "url": "https://evolve.routestack.ai/checkout"}

    client._post = fake_post  # type: ignore[method-assign]
    option = FlightOption(
        offer_id="fare-1",
        airlines=("Test Air",),
        airline_codes=("TA",),
        legs=(
            Leg(
                origin="JFK",
                destination="LAX",
                departure=datetime(2026, 11, 6, 8),
                arrival=datetime(2026, 11, 6, 11),
                duration_minutes=180,
                stops=0,
            ),
        ),
        total_price=250,
        currency="USD",
        checked_bags=1,
        booking_payload={"fareSourceCode": "fare-1"},
        search_filter={"adults": 1},
    )
    request = SearchRequest(
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

    url = asyncio.run(client.create_checkout_url(option, request))

    assert url == "https://evolve.routestack.ai/checkout"
    assert calls[0][0] == "/mcp/flight/revalidate"
    assert calls[0][1]["fareSourceCode"] == "fare-1"
    assert calls[1][0] == "/mcp/flight/get-payment-url"
    assert calls[1][1]["flight"] == {"fresh": True}
    asyncio.run(client.close())


def test_identical_search_uses_short_lived_cache() -> None:
    client = RouteStackClient(settings())
    calls = 0

    async def fake_post(path: str, body: dict) -> dict:
        nonlocal calls
        calls += 1
        return {
            "currency": "USD",
            "result": [
                {
                    "fareSourceCode": "cached-fare",
                    "showOurprice": 200,
                    "flights": [
                        {
                            "departure": "JFK",
                            "arrival": "LAX",
                            "departureTime": "2026-11-06T08:00:00",
                            "arrivalTime": "2026-11-06T11:00:00",
                        }
                    ],
                }
            ],
        }

    client._post = fake_post  # type: ignore[method-assign]
    search_request = SearchRequest(
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

    async def run_twice() -> tuple[list[FlightOption], list[FlightOption]]:
        first = await client._search_dates(
            search_request, "JFK", "LAX", date(2026, 11, 6), None
        )
        second = await client._search_dates(
            search_request, "JFK", "LAX", date(2026, 11, 6), None
        )
        await client.close()
        return first, second

    first, second = asyncio.run(run_twice())
    assert calls == 1
    assert first[0].offer_id == second[0].offer_id
    assert any("cached fare" in warning.lower() for warning in second[0].warnings)


def test_auto_nearby_is_on_domestic_and_off_international() -> None:
    async def run_route(destination: str, destination_country: str) -> SearchRequest:
        client = RouteStackClient(settings())

        async def fake_resolve(query: str, find_alternatives: bool = False):
            if query == "JFK":
                alternatives = ["EWR"] if find_alternatives else []
                return "JFK", "New York JFK", alternatives, "US"
            return destination, destination, [], destination_country

        async def fake_search_dates(*args, **kwargs):
            return []

        client.resolve_location = fake_resolve  # type: ignore[method-assign]
        client._search_dates = fake_search_dates  # type: ignore[method-assign]
        search_request = SearchRequest(
            origin="JFK",
            destination=destination,
            departure_date=date(2026, 11, 6),
            return_date=date(2026, 11, 13),
            adults=1,
            cabin=Cabin.ECONOMY,
            flexible_dates=False,
            nearby_airports=False,
            checked_bags=0,
            auto_nearby=True,
        )
        await client.search(search_request)
        await client.close()
        return search_request

    domestic = asyncio.run(run_route("LAX", "US"))
    international = asyncio.run(run_route("LHR", "GB"))
    assert domestic.nearby_airports is True
    assert international.nearby_airports is False
