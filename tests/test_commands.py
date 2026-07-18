import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from flight_bot.bot import BAGS, flexible, parse_flight_command
from flight_bot.models import Cabin, Priority


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
