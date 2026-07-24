import asyncio

from flight_bot.airports import (
    is_domestic,
    local_airport,
    local_airport_suggestions,
    smart_baggage,
)
from flight_bot.config import Settings
from flight_bot.routestack import RouteStackClient


def settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:test",
        routestack_api_key="public-key",
        routestack_api_secret="private-secret",
    )


def test_local_airports_detect_domestic_and_international_baggage() -> None:
    jfk = local_airport("JFK")
    lax = local_airport("LAX")
    lhr = local_airport("LHR")
    assert jfk and lax and lhr
    assert smart_baggage(jfk[2], lax[2]) == (0, 1)
    assert smart_baggage(jfk[2], lhr[2]) == (2, 1)
    assert is_domestic(jfk[2], lax[2]) is True
    assert is_domestic(jfk[2], lhr[2]) is False


def test_city_state_airport_suggestions_are_local_and_useful() -> None:
    new_york = local_airport_suggestions("New York, NY")
    assert [item[0] for item in new_york[:3]] == ["JFK", "LGA", "EWR"]
    london_ontario = local_airport_suggestions("London, Ontario")
    assert london_ontario
    assert london_ontario[0][2] == "CA"


def test_exact_iata_resolution_does_not_call_provider() -> None:
    client = RouteStackClient(settings())

    async def fail_post(*args, **kwargs):
        raise AssertionError("RouteStack should not be called for an exact IATA code")

    client._post = fail_post  # type: ignore[method-assign]
    code, label, alternatives, country = asyncio.run(
        client.resolve_location("JFK")
    )
    assert code == "JFK"
    assert "John F Kennedy" in label
    assert alternatives == []
    assert country == "US"
    asyncio.run(client.close())


def test_exact_iata_label_includes_full_city_and_subdivision() -> None:
    clt = local_airport("CLT")
    assert clt
    assert clt[0] == "CLT"
    assert "Charlotte Douglas International Airport" in clt[1]
    assert "Charlotte" in clt[1]
    assert "North Carolina" in clt[1]
    assert clt[2] == "US"
