from __future__ import annotations

import shlex


def command_arguments(message_text: str, fallback: list[str]) -> list[str]:
    """Parse normal command args or `origin | destination | date options`."""
    _, separator, body = message_text.partition(" ")
    if not separator or "|" not in body:
        return fallback
    sections = [section.strip() for section in body.split("|", 2)]
    if len(sections) != 3 or not all(sections):
        raise ValueError(
            "use: origin city | destination city | YYYY-MM-DD and options"
        )
    try:
        date_and_options = shlex.split(sections[2])
    except ValueError as exc:
        raise ValueError("the command contains unmatched quotation marks") from exc
    if not date_and_options:
        raise ValueError("departure date is required")
    return [sections[0], sections[1], *date_and_options]
