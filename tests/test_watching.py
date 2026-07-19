from datetime import date, datetime, timezone

from flight_bot.config import Settings
from flight_bot.models import Cabin
from flight_bot.watch_store import request_from_json, request_to_json
from flight_bot.watch_store import Watch
from flight_bot.watching import (
    _alert_reasons,
    observed_price_guidance,
    parse_watch_command,
)


def settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:test",
        routestack_api_key="public-key",
        routestack_api_secret="private-secret",
        owner_telegram_user_id=123,
        database_url="postgresql://example",
    )


def test_watch_safe_defaults_use_one_exact_search() -> None:
    pending = parse_watch_command(
        ["JFK", "LAX", "2026-09-15"],
        settings(),
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    assert pending.request.return_date == date(2026, 9, 22)
    assert pending.request.adults == 1
    assert pending.request.cabin == Cabin.ECONOMY
    assert pending.request.flexible_dates is False
    assert pending.request.nearby_airports is False
    assert pending.interval_hours == 24
    assert pending.drop_percent == 5
    assert pending.maximum_checks <= 60


def test_watch_overrides_and_request_round_trip_serialization() -> None:
    pending = parse_watch_command(
        [
            "JFK",
            "LHR",
            "2026-09-15",
            "--return",
            "2026-09-25",
            "--target",
            "500",
            "--drop",
            "10",
            "--every",
            "12",
            "--for-days",
            "20",
            "--cabin",
            "business",
            "--prefer",
            "BA,AA",
        ],
        settings(),
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    restored = request_from_json(request_to_json(pending.request))
    assert pending.target_price == 500
    assert pending.drop_percent == 10
    assert pending.interval_hours == 12
    assert restored.return_date == date(2026, 9, 25)
    assert restored.cabin == Cabin.BUSINESS
    assert restored.preferred_airlines == {"BA", "AA"}


def test_observed_guidance_uses_only_watch_history() -> None:
    assert "more checks" in observed_price_guidance([500])
    assert "lowest price observed" in observed_price_guidance([500, 450])
    assert "increased" in observed_price_guidance([400, 420, 440])


def test_alerts_are_meaningful_and_deduplicated() -> None:
    pending = parse_watch_command(
        ["JFK", "LAX", "2026-09-15", "--target", "450"],
        settings(),
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    watch = Watch(
        id="00000000-0000-0000-0000-000000000001",
        user_id=123,
        request=pending.request,
        target_price=450,
        drop_percent=5,
        interval_hours=24,
        expires_at=pending.expires_at,
        next_check_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        last_price=500,
        record_low=480,
    )
    assert set(_alert_reasons(watch, 440)) == {
        "target price reached",
        "price dropped 12.0%",
        "new record low",
    }
    watch.last_alert_price = 440
    assert _alert_reasons(watch, 440) == []
