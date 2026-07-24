from datetime import date

from fastapi.testclient import TestClient

from flight_bot.api import TripPayload, create_api
from flight_bot.config import Settings
from flight_bot.models import Cabin, Priority


def settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:test",
        routestack_api_key="public-key",
        routestack_api_secret="private-secret",
        owner_telegram_user_id=123,
        app_access_token="a-long-private-app-token",
    )


def test_api_root_is_live_without_exposing_configuration() -> None:
    with TestClient(create_api(settings())) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "service": "Flight Companion API",
        "status": "running",
    }


def test_api_rejects_missing_owner_bearer_token() -> None:
    with TestClient(create_api(settings())) as client:
        response = client.get("/api/v1/airports?q=New%20York")
    assert response.status_code == 401


def test_airport_api_expands_exact_iata_code_without_provider_call() -> None:
    with TestClient(create_api(settings())) as client:
        response = client.get(
            "/api/v1/airports?q=CLT",
            headers={"Authorization": "Bearer a-long-private-app-token"},
        )
    assert response.status_code == 200
    assert response.json() == [
        {
            "code": "CLT",
            "label": (
                "[CLT] Charlotte Douglas International Airport, Charlotte, "
                "North Carolina, US"
            ),
            "country": "US",
        }
    ]


def test_trip_payload_maps_every_safe_default() -> None:
    payload = TripPayload(
        origin="JFK",
        destination="LAX",
        departure_date=date(2026, 9, 15),
        return_date=date(2026, 9, 22),
    )
    request = payload.request()
    assert request.adults == 4
    assert request.cabin == Cabin.ECONOMY
    assert request.priority == Priority.BALANCED
    assert request.flexible_days == 3
    assert request.auto_nearby is True
    assert request.checked_bags == 2
    assert request.carry_on_bags == 1
    assert request.avoid_red_eye is True


def test_trip_payload_maps_required_airlines() -> None:
    payload = TripPayload(
        origin="CLT",
        destination="LAX",
        departure_date=date(2026, 9, 15),
        required_airlines=["aa", "DL"],
    )
    assert payload.request().required_airlines == {"AA", "DL"}
