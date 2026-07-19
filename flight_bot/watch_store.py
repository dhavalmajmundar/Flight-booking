from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import asyncpg

from .models import Cabin, Priority, SearchRequest


@dataclass
class Watch:
    id: str
    user_id: int
    request: SearchRequest
    target_price: float | None
    drop_percent: float
    interval_hours: int
    expires_at: datetime
    next_check_at: datetime
    last_checked_at: datetime | None = None
    last_price: float | None = None
    record_low: float | None = None
    last_alert_price: float | None = None
    active: bool = True
    expiry_reminded: bool = False

    @property
    def short_id(self) -> str:
        return self.id.split("-", 1)[0]


def request_to_json(request: SearchRequest) -> str:
    payload = {
        "origin": request.origin,
        "destination": request.destination,
        "departure_date": request.departure_date.isoformat(),
        "return_date": (
            request.return_date.isoformat() if request.return_date else None
        ),
        "adults": request.adults,
        "cabin": request.cabin.value,
        "flexible_dates": False,
        "nearby_airports": False,
        "checked_bags": request.checked_bags,
        "carry_on_bags": request.carry_on_bags,
        "auto_baggage": request.auto_baggage,
        "auto_nearby": False,
        "preferred_airlines": sorted(request.preferred_airlines),
        "avoided_airlines": sorted(request.avoided_airlines),
        "max_budget": request.max_budget,
        "priority": request.priority.value,
        "currency": request.currency,
    }
    return json.dumps(payload, separators=(",", ":"))


def request_from_json(raw: str | dict[str, Any]) -> SearchRequest:
    payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
    payload["departure_date"] = date.fromisoformat(payload["departure_date"])
    payload["return_date"] = (
        date.fromisoformat(payload["return_date"])
        if payload.get("return_date")
        else None
    )
    payload["cabin"] = Cabin(payload["cabin"])
    payload["priority"] = Priority(payload["priority"])
    payload["preferred_airlines"] = set(payload.get("preferred_airlines", []))
    payload["avoided_airlines"] = set(payload.get("avoided_airlines", []))
    return SearchRequest(**payload)


class WatchStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.database_url, min_size=1, max_size=3, command_timeout=30
        )
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flight_watches (
                    id UUID PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    request_json JSONB NOT NULL,
                    target_price DOUBLE PRECISION,
                    drop_percent DOUBLE PRECISION NOT NULL DEFAULT 5,
                    interval_hours INTEGER NOT NULL DEFAULT 24,
                    expires_at TIMESTAMPTZ NOT NULL,
                    next_check_at TIMESTAMPTZ NOT NULL,
                    last_checked_at TIMESTAMPTZ,
                    last_price DOUBLE PRECISION,
                    record_low DOUBLE PRECISION,
                    last_alert_price DOUBLE PRECISION,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    expiry_reminded BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS flight_watches_due_idx
                    ON flight_watches (active, next_check_at);

                CREATE TABLE IF NOT EXISTS watch_prices (
                    id BIGSERIAL PRIMARY KEY,
                    watch_id UUID NOT NULL REFERENCES flight_watches(id)
                        ON DELETE CASCADE,
                    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    price DOUBLE PRECISION NOT NULL,
                    currency TEXT NOT NULL,
                    airline TEXT,
                    duration_minutes INTEGER,
                    stops INTEGER
                );
                CREATE INDEX IF NOT EXISTS watch_prices_history_idx
                    ON watch_prices (watch_id, checked_at DESC);

                CREATE TABLE IF NOT EXISTS watch_usage (
                    usage_date DATE PRIMARY KEY,
                    attempts INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS watch_notifications (
                    user_id BIGINT NOT NULL,
                    notification_key TEXT NOT NULL,
                    last_sent_date DATE NOT NULL,
                    PRIMARY KEY (user_id, notification_key)
                );
                """
            )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    def _require_pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Watch database is not initialized.")
        return self.pool

    @staticmethod
    def _watch(row: asyncpg.Record) -> Watch:
        return Watch(
            id=str(row["id"]),
            user_id=row["user_id"],
            request=request_from_json(row["request_json"]),
            target_price=(
                float(row["target_price"])
                if row["target_price"] is not None
                else None
            ),
            drop_percent=float(row["drop_percent"]),
            interval_hours=row["interval_hours"],
            expires_at=row["expires_at"],
            next_check_at=row["next_check_at"],
            last_checked_at=row["last_checked_at"],
            last_price=(
                float(row["last_price"])
                if row["last_price"] is not None
                else None
            ),
            record_low=(
                float(row["record_low"])
                if row["record_low"] is not None
                else None
            ),
            last_alert_price=(
                float(row["last_alert_price"])
                if row["last_alert_price"] is not None
                else None
            ),
            active=row["active"],
            expiry_reminded=row["expiry_reminded"],
        )

    @staticmethod
    def _uuid(value: str) -> uuid.UUID:
        return uuid.UUID(value)

    async def count_active(self, user_id: int) -> int:
        value = await self._require_pool().fetchval(
            "SELECT COUNT(*) FROM flight_watches WHERE user_id=$1 AND active",
            user_id,
        )
        return int(value or 0)

    async def create_watch(
        self,
        user_id: int,
        request: SearchRequest,
        target_price: float | None,
        drop_percent: float,
        interval_hours: int,
        expires_at: datetime,
    ) -> Watch:
        watch_id = uuid.uuid4()
        row = await self._require_pool().fetchrow(
            """
            INSERT INTO flight_watches (
                id, user_id, request_json, target_price, drop_percent,
                interval_hours, expires_at, next_check_at
            )
            VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, NOW())
            RETURNING *
            """,
            watch_id,
            user_id,
            request_to_json(request),
            target_price,
            drop_percent,
            interval_hours,
            expires_at,
        )
        return self._watch(row)

    async def list_active(self, user_id: int) -> list[Watch]:
        rows = await self._require_pool().fetch(
            """
            SELECT * FROM flight_watches
            WHERE user_id=$1 AND active
            ORDER BY created_at
            """,
            user_id,
        )
        return [self._watch(row) for row in rows]

    async def get_by_prefix(self, user_id: int, prefix: str) -> Watch | None:
        rows = await self._require_pool().fetch(
            """
            SELECT * FROM flight_watches
            WHERE user_id=$1 AND id::text ILIKE $2 AND active
            ORDER BY created_at DESC LIMIT 2
            """,
            user_id,
            f"{prefix}%",
        )
        return self._watch(rows[0]) if len(rows) == 1 else None

    async def deactivate(self, user_id: int, prefix: str) -> bool:
        watch = await self.get_by_prefix(user_id, prefix)
        if not watch:
            return False
        result = await self._require_pool().execute(
            """
            UPDATE flight_watches SET active=FALSE
            WHERE user_id=$1 AND id=$2::uuid AND active
            """,
            user_id,
            self._uuid(watch.id),
        )
        return result != "UPDATE 0"

    async def due_watches(self, limit: int = 10) -> list[Watch]:
        rows = await self._require_pool().fetch(
            """
            SELECT * FROM flight_watches
            WHERE active AND next_check_at <= NOW() AND expires_at > NOW()
            ORDER BY next_check_at LIMIT $1
            """,
            limit,
        )
        return [self._watch(row) for row in rows]

    async def claim(self, watch: Watch) -> bool:
        result = await self._require_pool().execute(
            """
            UPDATE flight_watches
            SET next_check_at = NOW() + make_interval(hours => interval_hours)
            WHERE id=$1::uuid AND active AND next_check_at <= NOW()
            """,
            self._uuid(watch.id),
        )
        return result != "UPDATE 0"

    async def schedule_now(self, user_id: int, prefix: str) -> bool:
        watch = await self.get_by_prefix(user_id, prefix)
        if not watch:
            return False
        result = await self._require_pool().execute(
            """
            UPDATE flight_watches SET next_check_at=NOW()
            WHERE user_id=$1 AND id=$2::uuid AND active
            """,
            user_id,
            self._uuid(watch.id),
        )
        return result != "UPDATE 0"

    async def usage_today(self) -> int:
        value = await self._require_pool().fetchval(
            "SELECT attempts FROM watch_usage WHERE usage_date=CURRENT_DATE"
        )
        return int(value or 0)

    async def increment_usage(self) -> int:
        value = await self._require_pool().fetchval(
            """
            INSERT INTO watch_usage (usage_date, attempts)
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT (usage_date)
            DO UPDATE SET attempts=watch_usage.attempts + 1
            RETURNING attempts
            """
        )
        return int(value)

    async def postpone_due_until_tomorrow(self) -> None:
        await self._require_pool().execute(
            """
            UPDATE flight_watches
            SET next_check_at=date_trunc('day', NOW()) + INTERVAL '1 day 5 minutes'
            WHERE active AND next_check_at <= NOW()
            """
        )

    async def record_success(
        self,
        watch: Watch,
        price: float,
        currency: str,
        airline: str,
        duration_minutes: int,
        stops: int,
        alerted: bool,
    ) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO watch_prices (
                        watch_id, price, currency, airline,
                        duration_minutes, stops
                    ) VALUES ($1::uuid, $2, $3, $4, $5, $6)
                    """,
                    self._uuid(watch.id),
                    price,
                    currency,
                    airline,
                    duration_minutes,
                    stops,
                )
                await connection.execute(
                    """
                    UPDATE flight_watches
                    SET last_checked_at=NOW(), last_price=$2,
                        record_low=LEAST(COALESCE(record_low, $2), $2),
                        last_alert_price=CASE WHEN $3 THEN $2
                            ELSE last_alert_price END
                    WHERE id=$1::uuid
                    """,
                    self._uuid(watch.id),
                    price,
                    alerted,
                )

    async def record_failure(self, watch_id: str) -> None:
        await self._require_pool().execute(
            "UPDATE flight_watches SET last_checked_at=NOW() WHERE id=$1::uuid",
            self._uuid(watch_id),
        )

    async def recent_prices(
        self, watch_id: str, days: int = 7
    ) -> list[tuple[datetime, float]]:
        rows = await self._require_pool().fetch(
            """
            SELECT checked_at, price FROM watch_prices
            WHERE watch_id=$1::uuid
              AND checked_at >= NOW() - make_interval(days => $2::int)
            ORDER BY checked_at
            """,
            self._uuid(watch_id),
            int(days),
        )
        return [(row["checked_at"], float(row["price"])) for row in rows]

    async def expiring_watches(self, user_id: int) -> list[Watch]:
        rows = await self._require_pool().fetch(
            """
            SELECT * FROM flight_watches
            WHERE user_id=$1 AND active AND NOT expiry_reminded
              AND expires_at <= NOW() + INTERVAL '48 hours'
              AND expires_at > NOW()
            """,
            user_id,
        )
        return [self._watch(row) for row in rows]

    async def mark_expiry_reminded(self, watch_id: str) -> None:
        await self._require_pool().execute(
            """
            UPDATE flight_watches SET expiry_reminded=TRUE
            WHERE id=$1::uuid
            """,
            self._uuid(watch_id),
        )

    async def expire_old(self) -> None:
        await self._require_pool().execute(
            "UPDATE flight_watches SET active=FALSE WHERE active AND expires_at <= NOW()"
        )

    async def notification_due(
        self, user_id: int, key: str, today: date
    ) -> bool:
        last = await self._require_pool().fetchval(
            """
            SELECT last_sent_date FROM watch_notifications
            WHERE user_id=$1 AND notification_key=$2
            """,
            user_id,
            key,
        )
        return last is None or last < today

    async def mark_notification(
        self, user_id: int, key: str, today: date
    ) -> None:
        await self._require_pool().execute(
            """
            INSERT INTO watch_notifications (
                user_id, notification_key, last_sent_date
            ) VALUES ($1, $2, $3)
            ON CONFLICT (user_id, notification_key)
            DO UPDATE SET last_sent_date=EXCLUDED.last_sent_date
            """,
            user_id,
            key,
            today,
        )
