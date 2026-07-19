import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

from flight_bot.bot import (
    BAGS,
    BOT_COMMANDS,
    _nearby_search_allowance,
    _progressive_search,
    access_gate,
    configure_bot_commands,
    flexible,
    parse_flight_command,
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
    assert trip["adults"] == 1
    assert trip["cabin"] == Cabin.ECONOMY
    assert trip["flexible_dates"] is True
    assert trip["nearby_airports"] is False
    assert trip["auto_nearby"] is True
    assert trip["auto_baggage"] is True
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


def test_guided_search_uses_automatic_nearby_default() -> None:
    message = SimpleNamespace(text="Yes", reply_text=AsyncMock())
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={"trip": {}})

    next_state = asyncio.run(flexible(update, context))

    assert next_state == BAGS
    assert context.user_data["trip"]["nearby_airports"] is False
    assert context.user_data["trip"]["auto_nearby"] is True


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
