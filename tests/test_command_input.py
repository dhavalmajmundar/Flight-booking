import pytest

from flight_bot.command_input import command_arguments


def test_pipe_format_preserves_multiword_cities_and_options() -> None:
    args = command_arguments(
        "/flight New York, NY | Los Angeles, CA | "
        "2026-09-15 --return 2026-09-22 --target 350",
        [],
    )
    assert args == [
        "New York, NY",
        "Los Angeles, CA",
        "2026-09-15",
        "--return",
        "2026-09-22",
        "--target",
        "350",
    ]


def test_normal_format_uses_telegram_arguments() -> None:
    fallback = ["JFK", "LAX", "2026-09-15"]
    assert command_arguments("/flight JFK LAX 2026-09-15", fallback) is fallback


def test_incomplete_pipe_format_is_rejected() -> None:
    with pytest.raises(ValueError, match="use:"):
        command_arguments("/flight New York | LAX", [])
