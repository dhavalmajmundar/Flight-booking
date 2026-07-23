from __future__ import annotations

import logging
import os
import sys
import threading

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
                settings.app_access_token or "",
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
    from .api import create_api
    import uvicorn

    api = create_api(settings)
    port = int(os.getenv("PORT", "8080"))
    threading.Thread(
        target=lambda: uvicorn.run(
            api, host="0.0.0.0", port=port, log_level="info"
        ),
        name="flight-app-api",
        daemon=True,
    ).start()
    logging.getLogger(__name__).info("Companion app API listening on port %d", port)
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
