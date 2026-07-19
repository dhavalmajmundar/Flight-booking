from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    routestack_api_key: str
    routestack_api_secret: str
    routestack_base_url: str = "https://mcp.routestack.ai"
    default_currency: str = "USD"
    max_results: int = 40
    search_cache_seconds: int = 300
    owner_telegram_user_id: int | None = None
    database_url: str | None = None
    watch_daily_token_cap: int = 10
    watch_max_active: int = 5
    watch_max_days: int = 60
    watch_digest_hour_utc: int = 13

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        required = {
            "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            "ROUTESTACK_API_KEY": os.getenv("ROUTESTACK_API_KEY", "").strip(),
            "ROUTESTACK_API_SECRET": os.getenv(
                "ROUTESTACK_API_SECRET", ""
            ).strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        owner_value = os.getenv("OWNER_TELEGRAM_USER_ID", "").strip()
        try:
            owner_id = int(owner_value) if owner_value else None
        except ValueError as exc:
            raise RuntimeError(
                "OWNER_TELEGRAM_USER_ID must be a numeric Telegram user ID."
            ) from exc

        return cls(
            telegram_bot_token=required["TELEGRAM_BOT_TOKEN"],
            routestack_api_key=required["ROUTESTACK_API_KEY"],
            routestack_api_secret=required["ROUTESTACK_API_SECRET"],
            routestack_base_url=os.getenv(
                "ROUTESTACK_BASE_URL", "https://mcp.routestack.ai"
            ).strip(),
            default_currency=os.getenv("DEFAULT_CURRENCY", "USD").strip().upper(),
            max_results=max(5, min(int(os.getenv("MAX_RESULTS", "40")), 100)),
            search_cache_seconds=max(
                0, min(int(os.getenv("SEARCH_CACHE_SECONDS", "300")), 900)
            ),
            owner_telegram_user_id=owner_id,
            database_url=os.getenv("DATABASE_URL", "").strip() or None,
            watch_daily_token_cap=max(
                1, min(int(os.getenv("WATCH_DAILY_TOKEN_CAP", "10")), 100)
            ),
            watch_max_active=max(
                1, min(int(os.getenv("WATCH_MAX_ACTIVE", "5")), 20)
            ),
            watch_max_days=max(
                1, min(int(os.getenv("WATCH_MAX_DAYS", "60")), 365)
            ),
            watch_digest_hour_utc=max(
                0, min(int(os.getenv("WATCH_DIGEST_HOUR_UTC", "13")), 23)
            ),
        )
