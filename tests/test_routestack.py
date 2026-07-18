from datetime import date

from flight_bot.config import Settings
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
