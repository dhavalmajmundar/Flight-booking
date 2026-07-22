import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

from flight_bot.bot import (
    BAGS,
    BUDGET,
    CARRY_ON,
    BOT_COMMANDS,
    FLEX_DAYS,
    NEARBY,
    PASSENGERS,
    PRIORITY,
    _nearby_search_allowance,
    _calendar_keyboard,
    _progressive_search,
    access_gate,
    configure_bot_commands,
    bags,
    carry_on,
    budget,
    common_budget_values,
    flexible,
    flexible_days,
    nearby,
    passengers,
    parse_flight_command,
    parse_quick_request,
    return_date,
    suggested_departure_date,
)
from flight_bot.models import Cabin, FlightOption, Leg, Priority, SearchRequest
from flight_bot.config import Settings


def future_date(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def test_minimal_flight_command_uses_safe_defaults() -> None:
    trip = parse_flight_command(["JFK", "LAX", future_date()])
    assert trip["origin"] == "JFK"
    assert trip["return_date"] == trip["departure_date"] + timedelta(days=7)
    assert trip["adults"] == 4
    assert trip["cabin"] == Cabin.ECONOMY
    assert trip["flexible_dates"] is True
    assert trip["flexible_days"] == 3
    assert trip["nearby_airports"] is False
    assert trip["auto_nearby"] is True
    assert trip["auto_baggage"] is False
    assert trip["checked_bags"] == 2
    assert trip["carry_on_bags"] == 1
    assert trip["priority"] == Priority.BALANCED


def test_full_flight_command() -> None:
    departure = future_date()
    returning = future_date(37)
    trip = parse_flight_command(
        [
            "JFK",
            "LAX",
            departure,
            "--return",
            returning,
            "--adults",
            "2",
            "--cabin",
            "business",
            "--flex",
            "yes",
            "--flex-days",
            "5",
            "--nearby",
            "no",
            "--bags",
            "1",
            "--prefer",
            "DL,UA",
            "--avoid",
            "NK,F9",
            "--budget",
            "1200",
            "--priority",
            "cheapest",
        ]
    )
    assert trip["return_date"].isoformat() == returning
    assert trip["adults"] == 2
    assert trip["cabin"] == Cabin.BUSINESS
    assert trip["preferred_airlines"] == {"DL", "UA"}
    assert trip["max_budget"] == 1200
    assert trip["priority"] == Priority.CHEAPEST
    assert trip["flexible_days"] == 5


def test_unknown_option_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown option"):
        parse_flight_command(["JFK", "LAX", future_date(), "--oops", "yes"])


def test_one_way_and_manual_baggage_override() -> None:
    trip = parse_flight_command(
        [
            "JFK",
            "LAX",
            future_date(),
            "--trip",
            "one-way",
            "--bags",
            "1",
            "--carry-on",
            "0",
            "--nearby",
            "no",
        ]
    )
    assert trip["return_date"] is None
    assert trip["auto_baggage"] is False
    assert trip["checked_bags"] == 1
    assert trip["carry_on_bags"] == 0
    assert trip["auto_nearby"] is False


def test_guided_search_collects_flexible_range_then_auto_nearby() -> None:
    message = SimpleNamespace(text="Yes", reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={"trip": {}})

    next_state = asyncio.run(flexible(update, context))
    assert next_state == FLEX_DAYS

    message.text = "±3 days (default)"
    next_state = asyncio.run(flexible_days(update, context))
    assert next_state == NEARBY
    assert context.user_data["trip"]["flexible_days"] == 3

    message.text = "Auto (recommended)"
    next_state = asyncio.run(nearby(update, context))
    assert next_state == BAGS
    assert context.user_data["trip"]["nearby_airports"] is False
    assert context.user_data["trip"]["auto_nearby"] is True


def test_guided_baggage_defaults_are_two_checked_and_one_carry_on() -> None:
    message = SimpleNamespace(text="2 checked (default)", reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={"trip": {}})

    assert asyncio.run(bags(update, context)) == CARRY_ON
    assert context.user_data["trip"]["checked_bags"] == 2
    assert context.user_data["trip"]["auto_baggage"] is False

    message.text = "1 carry-on (default)"
    asyncio.run(carry_on(update, context))
    assert context.user_data["trip"]["carry_on_bags"] == 1


def test_common_budget_buttons_scale_by_route_cabin_and_passengers() -> None:
    domestic = {
        "origin": "JFK",
        "destination": "LAX",
        "cabin": Cabin.ECONOMY,
        "adults": 4,
        "return_date": date.today() + timedelta(days=30),
    }
    international = {
        **domestic,
        "destination": "LHR",
    }
    business = {**international, "cabin": Cabin.BUSINESS}

    assert common_budget_values(domestic) == (1500, 2000, 2500, 3500)
    assert common_budget_values(
        {**domestic, "origin": "New York, NY", "destination": "Los Angeles, CA"}
    ) == (1500, 2000, 2500, 3500)
    assert common_budget_values(international) == (3000, 4000, 5000, 7000)
    assert min(common_budget_values(business)) > max(
        common_budget_values(international)
    )
    assert len(common_budget_values({**domestic, "adults": 1})) == 4


def test_custom_budget_button_requests_an_amount_without_advancing() -> None:
    message = SimpleNamespace(text="Custom amount", reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={"trip": {}})

    next_state = asyncio.run(budget(update, context))

    assert next_state == BUDGET
    assert "custom maximum" in message.reply_text.await_args.args[0].lower()

    message.text = "2750"
    assert asyncio.run(budget(update, context)) == PRIORITY
    assert context.user_data["trip"]["max_budget"] == 2750
    keyboard = message.reply_text.await_args.kwargs["reply_markup"]
    assert [button.text for button in keyboard.keyboard[0]] == [
        "Cheapest",
        "Balanced (default)",
    ]
    assert [button.text for button in keyboard.keyboard[1]] == [
        "Fastest",
        "Nonstop",
    ]


def test_guided_round_trip_uses_duration_and_four_passenger_default_button() -> None:
    departure_day = date.today() + timedelta(days=30)
    message = SimpleNamespace(text="7 days (default)", reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={"trip": {"departure_date": departure_day}})

    next_state = asyncio.run(return_date(update, context))

    assert context.user_data["trip"]["return_date"] == departure_day + timedelta(days=7)
    assert next_state == PASSENGERS
    keyboard = message.reply_text.await_args.kwargs["reply_markup"]
    assert any(
        button.text == "4 (default)"
        for row in keyboard.keyboard
        for button in row
    )

    message.text = "4 (default)"
    asyncio.run(passengers(update, context))
    assert context.user_data["trip"]["adults"] == 4


def test_calendar_keyboard_has_future_date_navigation_without_api_calls() -> None:
    today = date.today()
    keyboard = _calendar_keyboard(today.year, today.month)
    callback_values = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }
    assert any(value and value.startswith("cal:pick:") for value in callback_values)
    assert any(value and value.startswith("cal:nav:") for value in callback_values)


def test_no_call_date_suggestion_prefers_nearby_midweek() -> None:
    friday = date(2026, 9, 18)
    assert friday.weekday() == 4
    assert suggested_departure_date(friday) == date(2026, 9, 16)


def test_no_call_token_estimate_uses_local_route_countries() -> None:
    base = {"auto_nearby": True, "nearby_airports": False, "origin": "JFK"}
    assert _nearby_search_allowance({**base, "destination": "LAX"}) == 4
    assert _nearby_search_allowance({**base, "destination": "LHR"}) == 0


def test_startup_registers_telegram_slash_menu() -> None:
    bot = SimpleNamespace(set_my_commands=AsyncMock())
    application = SimpleNamespace(bot=bot)

    asyncio.run(configure_bot_commands(application))

    bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)
    assert [command.command for command in BOT_COMMANDS] == [
        "start",
        "search",
        "flight",
        "quick",
        "watch",
        "watches",
        "history",
        "checknow",
        "usage",
        "unwatch",
        "airports",
        "recent",
        "repeat",
        "profile",
        "defaults",
        "help",
        "cancel",
        "myid",
    ]


def test_quick_request_parses_city_names_date_and_duration() -> None:
    args = parse_quick_request(
        "New York, NY to Paris on October 10, 2026 for 8 days"
    )
    assert args == [
        "New York, NY",
        "Paris",
        "2026-10-10",
        "--nights",
        "8",
    ]


def test_access_gate_blocks_non_owner_before_other_handlers() -> None:
    message = SimpleNamespace(text="/search", reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_message=message,
        callback_query=None,
    )
    settings = Settings(
        telegram_bot_token="123456:test",
        routestack_api_key="public",
        routestack_api_secret="secret",
        owner_telegram_user_id=123,
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": settings})
    )
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(access_gate(update, context))
    message.reply_text.assert_awaited_once_with("This is a private bot.")


def test_access_gate_allows_owner_and_myid_without_provider_access() -> None:
    settings = Settings(
        telegram_bot_token="123456:test",
        routestack_api_key="public",
        routestack_api_secret="secret",
        owner_telegram_user_id=123,
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": settings})
    )
    owner_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_message=SimpleNamespace(text="/search"),
        callback_query=None,
    )
    assert asyncio.run(access_gate(owner_update, context)) is None

    unlocked_settings = Settings(
        telegram_bot_token="123456:test",
        routestack_api_key="public",
        routestack_api_secret="secret",
        owner_telegram_user_id=None,
    )
    unlocked_context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"settings": unlocked_settings})
    )
    message = SimpleNamespace(text="/myid", reply_text=AsyncMock())
    id_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_message=message,
        callback_query=None,
    )
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(access_gate(id_update, unlocked_context))
    assert "999" in message.reply_text.await_args.args[0]

    locked_message = SimpleNamespace(text="/myid", reply_text=AsyncMock())
    locked_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_message=locked_message,
        callback_query=None,
    )
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(access_gate(locked_update, context))
    locked_message.reply_text.assert_awaited_once_with("This is a private bot.")


def test_progressive_search_stops_after_safe_first_stage() -> None:
    departure = date.today() + timedelta(days=45)
    request = SearchRequest(
        origin="JFK",
        destination="LAX",
        departure_date=departure,
        return_date=departure + timedelta(days=7),
        adults=1,
        cabin=Cabin.ECONOMY,
        flexible_dates=True,
        nearby_airports=False,
        checked_bags=0,
        auto_nearby=True,
    )
    option = FlightOption(
        offer_id="safe",
        airlines=("Test Air",),
        airline_codes=("TA",),
        legs=(
            Leg(
                origin="JFK",
                destination="LAX",
                departure=datetime.combine(departure, datetime.min.time()),
                arrival=datetime.combine(departure, datetime.min.time())
                + timedelta(hours=6),
                duration_minutes=360,
                stops=0,
            ),
        ),
        total_price=300,
        currency="USD",
        checked_bags=0,
        carry_on_bags=1,
    )
    client = SimpleNamespace(
        search=AsyncMock(return_value=([option], "JFK", "LAX"))
    )
    result = asyncio.run(_progressive_search(client, request))
    assert len(result[0]) == 1
    assert "stopped after 1" in result[4]
    assert client.search.await_count == 1
