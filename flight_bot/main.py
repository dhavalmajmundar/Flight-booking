from __future__ import annotations

import logging
import sys

from .bot import build_application
from .config import Settings


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: tuple[str, ...]) -> None:
        super().__init__(fmt)
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        for secret in self.secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        return rendered


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            (
                settings.telegram_bot_token,
                settings.routestack_api_key,
                settings.routestack_api_secret,
                settings.database_url or "",
            ),
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # HTTPX logs full Telegram Bot API URLs, which contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings)
    application = build_application(settings)
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
