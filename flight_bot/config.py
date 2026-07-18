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
        )
