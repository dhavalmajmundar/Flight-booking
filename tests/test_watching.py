from datetime import date, datetime, timezone

from flight_bot.config import Settings
from flight_bot.models import Cabin
from flight_bot.watch_store import request_from_json, request_to_json
from flight_bot.watch_store import Watch
from flight_bot.watching import (
    _alert_reasons,
    _sparkline,
    adaptive_watch_interval_hours,
    observed_price_guidance,
    parse_watch_command,
    quiet_deferral_hours,
    watch_urgency_key,
)
from types import SimpleNamespace


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
    assert pending.request.adults == 4
    assert pending.request.cabin == Cabin.ECONOMY
    assert pending.request.flexible_dates is False
    assert pending.request.nearby_airports is False
    assert pending.request.checked_bags == 2
    assert pending.request.carry_on_bags == 1
    assert pending.request.auto_baggage is False
    assert pending.interval_hours == 24
    assert pending.drop_percent == 5
    assert pending.weekly_flex is False
    assert 60 < pending.maximum_checks <= 240


def test_watch_can_enable_weekly_flexible_deep_scan() -> None:
    pending = parse_watch_command(
        ["JFK", "LAX", "2026-09-15", "--weekly-flex", "yes"],
        settings(),
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    assert pending.weekly_flex is True
    assert pending.request.flexible_dates is False


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
            "--bags",
            "auto",
            "--carry-on",
            "2",
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
    pending.request.required_airlines = {"BA"}
    restored = request_from_json(request_to_json(pending.request))
    assert restored.required_airlines == {"BA"}
    assert restored.max_layover_minutes == 300
    assert restored.flexible_days == 0
    assert restored.auto_baggage is True
    assert restored.carry_on_bags == 2


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


def test_adaptive_watch_schedule_saves_calls_far_out_and_increases_urgency() -> None:
    pending = parse_watch_command(
        ["JFK", "LAX", "2026-12-20"],
        settings(),
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    watch = Watch(
        id="00000000-0000-0000-0000-000000000002",
        user_id=123,
        request=pending.request,
        target_price=450,
        drop_percent=5,
        interval_hours=24,
        expires_at=pending.expires_at,
        next_check_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        last_price=600,
    )
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    assert adaptive_watch_interval_hours(watch, now) == 48
    watch.request.departure_date = date(2026, 7, 30)
    assert adaptive_watch_interval_hours(watch, now) == 12
    watch.last_price = 460
    assert watch_urgency_key(watch, now)[0] < 1


def test_quiet_hours_defer_nonurgent_but_not_near_target() -> None:
    pending = parse_watch_command(
        ["JFK", "LAX", "2026-12-20", "--target", "500"], settings(),
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    watch = Watch(
        id="00000000-0000-0000-0000-000000000003", user_id=123,
        request=pending.request, target_price=500, drop_percent=5,
        interval_hours=24, expires_at=pending.expires_at,
        next_check_at=datetime(2026, 7, 19, tzinfo=timezone.utc), last_price=700,
    )
    profile = SimpleNamespace(timezone="America/New_York", quiet_start_hour=22, quiet_end_hour=7)
    now = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)  # 11 PM EDT
    assert quiet_deferral_hours(profile, watch, now) > 0
    watch.last_price = 520
    assert quiet_deferral_hours(profile, watch, now) == 0


def test_sparkline_uses_stored_values_without_external_service() -> None:
    chart = _sparkline([100, 120, 90, 140])
    assert len(chart) == 4
    assert chart[-1] == "█"
