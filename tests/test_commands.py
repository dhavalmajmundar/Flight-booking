from datetime import date, timedelta

import pytest

from flight_bot.bot import parse_flight_command
from flight_bot.models import Cabin, Priority


def future_date(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def test_minimal_flight_command_uses_safe_defaults() -> None:
    trip = parse_flight_command(["JFK", "LAX", future_date()])
    assert trip["origin"] == "JFK"
    assert trip["return_date"] is None
    assert trip["adults"] == 1
    assert trip["cabin"] == Cabin.ECONOMY
    assert trip["flexible_dates"] is False
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
