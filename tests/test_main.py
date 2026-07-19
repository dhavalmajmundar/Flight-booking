import logging

from flight_bot.main import RedactingFormatter


def test_log_formatter_redacts_all_configured_secrets() -> None:
    formatter = RedactingFormatter(
        "%(levelname)s %(message)s",
        ("telegram-secret", "route-secret", "postgres-secret"),
    )
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            "https://api.telegram.org/bottelegram-secret/getMe "
            "route-secret postgres-secret"
        ),
        args=(),
        exc_info=None,
    )
    rendered = formatter.format(record)
    assert "telegram-secret" not in rendered
    assert "route-secret" not in rendered
    assert "postgres-secret" not in rendered
    assert rendered.count("[REDACTED]") == 3
