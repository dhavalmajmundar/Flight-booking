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


@dataclass(frozen=True)
class UserProfile:
    preferred_airlines: set[str]
    avoided_airlines: set[str]
    max_budget: float | None
    max_layover_minutes: int


@dataclass(frozen=True)
class RecentSearch:
    id: int
    request: SearchRequest
    origin_code: str
    destination_code: str
    best_price: float
    currency: str
    created_at: datetime


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
        "max_layover_minutes": request.max_layover_minutes,
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
    payload.setdefault("max_layover_minutes", 300)
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

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id BIGINT PRIMARY KEY,
                    preferred_airlines TEXT[] NOT NULL DEFAULT '{}',
                    avoided_airlines TEXT[] NOT NULL DEFAULT '{}',
                    max_budget DOUBLE PRECISION,
                    max_layover_minutes INTEGER NOT NULL DEFAULT 300,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS recent_searches (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    request_json JSONB NOT NULL,
                    origin_code TEXT NOT NULL,
                    destination_code TEXT NOT NULL,
                    best_price DOUBLE PRECISION NOT NULL,
                    currency TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS recent_searches_user_idx
                    ON recent_searches (user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS recent_searches_route_idx
                    ON recent_searches (
                        user_id, origin_code, destination_code, currency,
                        created_at DESC
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

    async def claim(
        self, watch: Watch, next_interval_hours: int | None = None
    ) -> bool:
        interval = next_interval_hours or watch.interval_hours
        result = await self._require_pool().execute(
            """
            UPDATE flight_watches
            SET next_check_at = NOW() + make_interval(hours => $2::int)
            WHERE id=$1::uuid AND active AND next_check_at <= NOW()
            """,
            self._uuid(watch.id),
            interval,
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

    async def latest_observation(
        self, watch_id: str
    ) -> tuple[float, int | None, int | None] | None:
        row = await self._require_pool().fetchrow(
            """
            SELECT price, duration_minutes, stops FROM watch_prices
            WHERE watch_id=$1::uuid ORDER BY checked_at DESC LIMIT 1
            """,
            self._uuid(watch_id),
        )
        if not row:
            return None
        return (
            float(row["price"]),
            (
                int(row["duration_minutes"])
                if row["duration_minutes"] is not None
                else None
            ),
            int(row["stops"]) if row["stops"] is not None else None,
        )

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

    async def get_profile(self, user_id: int) -> UserProfile:
        row = await self._require_pool().fetchrow(
            "SELECT * FROM user_profiles WHERE user_id=$1", user_id
        )
        if not row:
            return UserProfile(set(), set(), None, 300)
        return UserProfile(
            preferred_airlines=set(row["preferred_airlines"] or []),
            avoided_airlines=set(row["avoided_airlines"] or []),
            max_budget=(
                float(row["max_budget"])
                if row["max_budget"] is not None
                else None
            ),
            max_layover_minutes=int(row["max_layover_minutes"]),
        )

    async def save_profile(
        self, user_id: int, profile: UserProfile
    ) -> UserProfile:
        await self._require_pool().execute(
            """
            INSERT INTO user_profiles (
                user_id, preferred_airlines, avoided_airlines,
                max_budget, max_layover_minutes
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                preferred_airlines=EXCLUDED.preferred_airlines,
                avoided_airlines=EXCLUDED.avoided_airlines,
                max_budget=EXCLUDED.max_budget,
                max_layover_minutes=EXCLUDED.max_layover_minutes,
                updated_at=NOW()
            """,
            user_id,
            sorted(profile.preferred_airlines),
            sorted(profile.avoided_airlines),
            profile.max_budget,
            profile.max_layover_minutes,
        )
        return profile

    async def record_search(
        self,
        user_id: int,
        request: SearchRequest,
        origin_code: str,
        destination_code: str,
        best_price: float,
        currency: str,
    ) -> None:
        await self._require_pool().execute(
            """
            INSERT INTO recent_searches (
                user_id, request_json, origin_code, destination_code,
                best_price, currency
            ) VALUES ($1, $2::jsonb, $3, $4, $5, $6)
            """,
            user_id,
            request_to_json(request),
            origin_code,
            destination_code,
            best_price,
            currency,
        )
        await self._require_pool().execute(
            """
            DELETE FROM recent_searches
            WHERE user_id=$1 AND id NOT IN (
                SELECT id FROM recent_searches
                WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50
            )
            """,
            user_id,
        )

    @staticmethod
    def _recent(row: asyncpg.Record) -> RecentSearch:
        return RecentSearch(
            id=int(row["id"]),
            request=request_from_json(row["request_json"]),
            origin_code=row["origin_code"],
            destination_code=row["destination_code"],
            best_price=float(row["best_price"]),
            currency=row["currency"],
            created_at=row["created_at"],
        )

    async def list_recent(
        self, user_id: int, limit: int = 5
    ) -> list[RecentSearch]:
        rows = await self._require_pool().fetch(
            """
            SELECT * FROM recent_searches
            WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2
            """,
            user_id,
            limit,
        )
        return [self._recent(row) for row in rows]

    async def get_recent(
        self, user_id: int, position: int
    ) -> RecentSearch | None:
        if position < 1:
            return None
        rows = await self.list_recent(user_id, limit=max(5, position))
        return rows[position - 1] if position <= len(rows) else None

    async def route_prices(
        self,
        user_id: int,
        origin_code: str,
        destination_code: str,
        currency: str,
        limit: int = 30,
    ) -> list[float]:
        rows = await self._require_pool().fetch(
            """
            SELECT best_price FROM recent_searches
            WHERE user_id=$1 AND origin_code=$2 AND destination_code=$3
              AND currency=$4
            ORDER BY created_at DESC LIMIT $5
            """,
            user_id,
            origin_code,
            destination_code,
            currency,
            limit,
        )
        return [float(row["best_price"]) for row in rows]
