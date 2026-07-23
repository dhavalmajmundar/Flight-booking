from __future__ import annotations

import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .airports import local_airport_suggestions
from .bot import _progressive_search, suggested_departure_date
from .config import Settings
from .links import expedia_search_url, google_flights_url, kayak_search_url
from .models import Cabin, DepartureWindow, FlightOption, Priority, SearchRequest
from .ranking import rank_flights
from .routestack import FlightSearchError, RouteStackClient
from .watch_store import UserProfile, Watch, WatchStore


class TripPayload(BaseModel):
    origin: str = Field(min_length=2, max_length=100)
    destination: str = Field(min_length=2, max_length=100)
    departure_date: date
    return_date: date | None = None
    adults: int = Field(default=4, ge=1, le=9)
    cabin: Cabin = Cabin.ECONOMY
    flexible_dates: bool = True
    flexible_days: int = Field(default=3, ge=0, le=7)
    nearby_mode: Literal["auto", "yes", "no"] = "auto"
    checked_bags: int = Field(default=2, ge=0, le=2)
    carry_on_bags: int = Field(default=1, ge=0, le=2)
    smart_baggage: bool = False
    preferred_airlines: list[str] = Field(default_factory=list)
    avoided_airlines: list[str] = Field(default_factory=list)
    max_budget: float | None = Field(default=None, gt=0)
    priority: Priority = Priority.BALANCED
    currency: Literal["USD", "CAD", "EUR", "GBP", "INR"] = "USD"
    departure_window: DepartureWindow = DepartureWindow.ANY
    avoid_red_eye: bool = True
    max_stops: int | None = Field(default=None, ge=0, le=2)
    min_layover_minutes: int = Field(default=60, ge=30, le=180)
    max_layover_minutes: int = Field(default=300, ge=60, le=720)
    max_total_duration_minutes: int | None = Field(default=None, ge=240, le=4320)
    search_mode: Literal["progressive", "suggested", "full", "exact"] = "progressive"

    def request(self) -> SearchRequest:
        if self.return_date and self.return_date <= self.departure_date:
            raise ValueError("return_date must be after departure_date")
        return SearchRequest(
            origin=self.origin.strip(), destination=self.destination.strip(),
            departure_date=self.departure_date, return_date=self.return_date,
            adults=self.adults, cabin=self.cabin,
            flexible_dates=self.flexible_dates and self.search_mode in {"progressive", "full"},
            flexible_days=self.flexible_days if self.flexible_dates else 0,
            nearby_airports=self.nearby_mode == "yes",
            auto_nearby=self.nearby_mode == "auto",
            checked_bags=self.checked_bags, carry_on_bags=self.carry_on_bags,
            auto_baggage=self.smart_baggage,
            preferred_airlines={value.upper() for value in self.preferred_airlines},
            avoided_airlines={value.upper() for value in self.avoided_airlines},
            max_budget=self.max_budget, priority=self.priority, currency=self.currency,
            departure_window=self.departure_window, avoid_red_eye=self.avoid_red_eye,
            max_stops=self.max_stops, min_layover_minutes=self.min_layover_minutes,
            max_layover_minutes=self.max_layover_minutes,
            max_total_duration_minutes=self.max_total_duration_minutes,
        )


class WatchPayload(BaseModel):
    trip: TripPayload
    target_price: float | None = Field(default=None, gt=0)
    drop_percent: float = Field(default=5, ge=1, le=50)
    interval_hours: Literal[6, 12, 24, 48] = 24
    duration_days: int = Field(default=30, ge=1, le=365)
    weekly_flex: bool = False


class WatchUpdatePayload(BaseModel):
    target_price: float | None = Field(default=None, gt=0)
    drop_percent: float = Field(default=5, ge=1, le=50)
    interval_hours: Literal[6, 12, 24, 48] = 24
    duration_days: int = Field(default=30, ge=1, le=365)
    weekly_flex: bool = False


class ProfilePayload(BaseModel):
    preferred_airlines: list[str] = Field(default_factory=list)
    avoided_airlines: list[str] = Field(default_factory=list)
    max_budget: float | None = Field(default=None, gt=0)
    max_layover_minutes: int = Field(default=300, ge=60, le=720)
    adults: int = Field(default=4, ge=1, le=9)
    cabin: Cabin = Cabin.ECONOMY
    checked_bags: int = Field(default=2, ge=0, le=2)
    carry_on_bags: int = Field(default=1, ge=0, le=2)
    currency: Literal["USD", "CAD", "EUR", "GBP", "INR"] = "USD"
    departure_window: DepartureWindow = DepartureWindow.ANY
    avoid_red_eye: bool = True
    max_stops: int | None = Field(default=None, ge=0, le=2)
    min_layover_minutes: int = Field(default=60, ge=30, le=180)
    max_total_duration_minutes: int | None = Field(default=None, ge=240, le=4320)
    timezone: str = "America/New_York"
    quiet_start_hour: int = Field(default=22, ge=0, le=23)
    quiet_end_hour: int = Field(default=7, ge=0, le=23)


def _watch_json(watch: Watch) -> dict[str, Any]:
    request = watch.request
    return {
        "id": watch.id, "short_id": watch.short_id,
        "origin": request.origin, "destination": request.destination,
        "departure_date": request.departure_date.isoformat(),
        "return_date": request.return_date.isoformat() if request.return_date else None,
        "adults": request.adults, "cabin": request.cabin.value,
        "currency": request.currency, "target_price": watch.target_price,
        "drop_percent": watch.drop_percent, "interval_hours": watch.interval_hours,
        "expires_at": watch.expires_at.isoformat(), "next_check_at": watch.next_check_at.isoformat(),
        "last_checked_at": watch.last_checked_at.isoformat() if watch.last_checked_at else None,
        "last_price": watch.last_price, "record_low": watch.record_low,
        "weekly_flex": watch.weekly_flex,
        "consecutive_failures": watch.consecutive_failures,
    }


def _option_json(
    option: FlightOption,
    request: SearchRequest,
    rank: int,
    tags: list[str],
    cheapest: FlightOption,
) -> dict[str, Any]:
    price_delta = option.total_price - cheapest.total_price
    minutes_saved = cheapest.duration_minutes - option.duration_minutes
    return {
        "rank": rank, "airlines": list(option.airlines), "airline_codes": list(option.airline_codes),
        "total_price": option.total_price, "per_traveler": option.total_price / request.adults,
        "currency": option.currency, "duration_minutes": option.duration_minutes,
        "tags": tags, "price_delta": price_delta,
        "minutes_saved_vs_cheapest": max(0, minutes_saved),
        "cost_per_hour_saved": (
            price_delta / (minutes_saved / 60)
            if price_delta > 0 and minutes_saved >= 30 else None
        ),
        "stops": option.stops, "checked_bags": option.checked_bags,
        "carry_on_bags": option.carry_on_bags, "warnings": list(dict.fromkeys(option.warnings)),
        "legs": [{
            "origin": leg.origin, "destination": leg.destination,
            "departure": leg.departure.isoformat(), "arrival": leg.arrival.isoformat(),
            "duration_minutes": leg.duration_minutes, "stops": leg.stops,
            "layovers": [{"airport": airport, "minutes": minutes} for airport, minutes in leg.layovers],
        } for leg in option.legs],
        "links": {
            "expedia": expedia_search_url(option, request),
            "google_flights": google_flights_url(option, request),
            "kayak": kayak_search_url(option, request),
        },
    }


def create_api(settings: Settings) -> FastAPI:
    state: dict[str, Any] = {"checkout": {}}
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        state["client"] = RouteStackClient(settings)
        if settings.database_url:
            state["store"] = WatchStore(settings.database_url)
            await state["store"].initialize()
        yield
        await state["client"].close()
        if state.get("store"):
            await state["store"].close()

    app = FastAPI(title="Flight Companion API", version="1.0", lifespan=lifespan)

    async def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        if not settings.app_access_token:
            raise HTTPException(503, "APP_ACCESS_TOKEN is not configured on Railway")
        if not credentials or not secrets.compare_digest(credentials.credentials, settings.app_access_token):
            raise HTTPException(401, "Invalid app access token")

    def store() -> WatchStore:
        value = state.get("store")
        if not value:
            raise HTTPException(503, "Railway Postgres is not configured")
        return value

    def owner() -> int:
        if settings.owner_telegram_user_id is None:
            raise HTTPException(503, "OWNER_TELEGRAM_USER_ID is not configured")
        return settings.owner_telegram_user_id

    @app.get("/")
    async def root():
        return {"service": "Flight Companion API", "status": "running"}

    @app.get("/api/v1/health", dependencies=[Depends(authorize)])
    async def health():
        db = bool(state.get("store") and await store().ping())
        return {"ok": True, "database": db, "route_stack": True,
                "active_watches": await store().count_active(owner()) if db else 0,
                "watch_usage_today": await store().usage_today() if db else 0,
                "watch_daily_cap": settings.watch_daily_token_cap}

    @app.get("/api/v1/airports", dependencies=[Depends(authorize)])
    async def airports(q: str):
        return [{"code": code, "label": label, "country": country}
                for code, label, country in local_airport_suggestions(q, limit=10)]

    @app.post("/api/v1/search", dependencies=[Depends(authorize)])
    async def search(payload: TripPayload):
        try:
            request = payload.request()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        client: RouteStackClient = state["client"]
        note = "single-date search"
        try:
            if payload.search_mode == "progressive" and payload.flexible_dates:
                offers, origin_label, destination_label, request, note = await _progressive_search(client, request)
            elif payload.search_mode == "suggested" and payload.flexible_dates:
                suggested = suggested_departure_date(request.departure_date, request.flexible_days)
                shift = suggested - request.departure_date
                request = replace(request, departure_date=suggested,
                                  return_date=request.return_date + shift if request.return_date else None,
                                  flexible_dates=False)
                offers, origin_label, destination_label = await client.search(request)
                note = "one no-call suggested-date candidate searched"
            else:
                if payload.search_mode == "exact":
                    request = replace(request, flexible_dates=False, nearby_airports=False, auto_nearby=False)
                offers, origin_label, destination_label = await client.search(request)
                note = "full flexible comparison" if request.flexible_dates else "exact-date search"
        except FlightSearchError as exc:
            raise HTTPException(502, str(exc)) from exc
        results = rank_flights(offers, request)
        if not results:
            return {"options": [], "origin_label": origin_label, "destination_label": destination_label, "search_note": note}
        selected = results.ordered[:8]
        checkout_token = secrets.token_urlsafe(12)
        state["checkout"][checkout_token] = (time.monotonic(), request, selected)
        for key, value in list(state["checkout"].items()):
            if time.monotonic() - value[0] > 900:
                state["checkout"].pop(key, None)
        lowest_by_date = [{"date": travel_date.isoformat(), "price": option.total_price, "currency": option.currency}
                          for travel_date, option in results.lowest_by_date]
        return {"origin_label": origin_label, "destination_label": destination_label,
                "search_note": note, "checkout_token": checkout_token,
                "lowest_by_date": lowest_by_date,
                "options": [
                    _option_json(
                        option, request, index + 1,
                        [label for label, candidate in (
                            ("Best overall", results.best_overall),
                            ("Cheapest", results.cheapest),
                            ("Fastest", results.fastest),
                            ("Best flexible date", results.best_flexible),
                        ) if candidate is option],
                        results.cheapest,
                    )
                    for index, option in enumerate(selected)
                ]}

    @app.post("/api/v1/checkout/{token}/{index}", dependencies=[Depends(authorize)])
    async def checkout(token: str, index: int):
        handoff = state["checkout"].get(token)
        if not handoff or time.monotonic() - handoff[0] > 900:
            raise HTTPException(410, "Search results expired; search again")
        _, request, options = handoff
        if index < 0 or index >= len(options):
            raise HTTPException(404, "Option not found")
        try:
            url = await state["client"].create_checkout_url(options[index], request)
        except FlightSearchError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"url": url, "notice": "Verify price, baggage, and fare rules before payment."}

    @app.get("/api/v1/profile", dependencies=[Depends(authorize)])
    async def get_profile():
        profile = await store().get_profile(owner())
        value = asdict(profile)
        value["cabin"] = profile.cabin.value
        value["departure_window"] = profile.departure_window.value
        value["preferred_airlines"] = sorted(profile.preferred_airlines)
        value["avoided_airlines"] = sorted(profile.avoided_airlines)
        return value

    @app.put("/api/v1/profile", dependencies=[Depends(authorize)])
    async def put_profile(payload: ProfilePayload):
        if payload.quiet_start_hour == payload.quiet_end_hour:
            raise HTTPException(422, "Quiet start and end must differ")
        profile = UserProfile(
            preferred_airlines={value.upper() for value in payload.preferred_airlines},
            avoided_airlines={value.upper() for value in payload.avoided_airlines},
            max_budget=payload.max_budget, max_layover_minutes=payload.max_layover_minutes,
            adults=payload.adults, cabin=payload.cabin, checked_bags=payload.checked_bags,
            carry_on_bags=payload.carry_on_bags, currency=payload.currency,
            departure_window=payload.departure_window, avoid_red_eye=payload.avoid_red_eye,
            max_stops=payload.max_stops, min_layover_minutes=payload.min_layover_minutes,
            max_total_duration_minutes=payload.max_total_duration_minutes,
            timezone=payload.timezone, quiet_start_hour=payload.quiet_start_hour,
            quiet_end_hour=payload.quiet_end_hour,
        )
        await store().save_profile(owner(), profile)
        return {"saved": True}

    @app.get("/api/v1/watches", dependencies=[Depends(authorize)])
    async def watches():
        return [_watch_json(watch) for watch in await store().list_active(owner())]

    @app.post("/api/v1/watches", dependencies=[Depends(authorize)])
    async def create_watch(payload: WatchPayload):
        request = payload.trip.request()
        request.flexible_dates = False
        request.flexible_days = 0
        request.nearby_airports = False
        request.auto_nearby = False
        duplicate = await store().find_duplicate(owner(), request)
        departure_cutoff = datetime.combine(request.departure_date, datetime_time(), tzinfo=timezone.utc) - timedelta(hours=12)
        expires = min(datetime.now(timezone.utc) + timedelta(days=payload.duration_days), departure_cutoff)
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(422, "Departure is too soon to monitor")
        if duplicate:
            return JSONResponse(status_code=409, content={"detail": "duplicate", "watch": _watch_json(duplicate)})
        if await store().count_active(owner()) >= settings.watch_max_active:
            raise HTTPException(409, "Active-watch limit reached")
        watch = await store().create_watch(owner(), request, payload.target_price,
                                           payload.drop_percent, payload.interval_hours,
                                           expires, payload.weekly_flex)
        return _watch_json(watch)

    @app.put("/api/v1/watches/{prefix}", dependencies=[Depends(authorize)])
    async def update_watch(prefix: str, payload: WatchUpdatePayload):
        watch = await store().get_by_prefix(owner(), prefix)
        if not watch:
            raise HTTPException(404, "Watch not found")
        cutoff = datetime.combine(watch.request.departure_date, datetime_time(), tzinfo=timezone.utc) - timedelta(hours=12)
        expires = min(datetime.now(timezone.utc) + timedelta(days=payload.duration_days), cutoff)
        updated = await store().update_watch_settings(watch.id, payload.target_price,
                                                      payload.drop_percent, payload.interval_hours,
                                                      expires, payload.weekly_flex)
        return _watch_json(updated)

    @app.delete("/api/v1/watches/{prefix}", dependencies=[Depends(authorize)])
    async def delete_watch(prefix: str):
        if not await store().deactivate(owner(), prefix):
            raise HTTPException(404, "Watch not found")
        return {"stopped": True}

    @app.post("/api/v1/watches/{prefix}/check", dependencies=[Depends(authorize)])
    async def check_watch(prefix: str):
        if await store().usage_today() >= settings.watch_daily_token_cap:
            raise HTTPException(429, "Daily watch-call cap reached")
        if not await store().schedule_now(owner(), prefix):
            raise HTTPException(404, "Watch not found")
        return {"queued": True}

    @app.post("/api/v1/watches/{prefix}/booked", dependencies=[Depends(authorize)])
    async def booked(prefix: str):
        if not await store().mark_booked(owner(), prefix):
            raise HTTPException(404, "Watch not found")
        return {"booked": True, "stopped": True}

    @app.get("/api/v1/watches/{prefix}/history", dependencies=[Depends(authorize)])
    async def history(prefix: str):
        watch = await store().get_by_prefix(owner(), prefix)
        if not watch:
            raise HTTPException(404, "Watch not found")
        return [{"checked_at": checked.isoformat(), "price": price,
                 "currency": watch.request.currency}
                for checked, price in await store().recent_prices(watch.id, days=60)]

    @app.get("/api/v1/usage", dependencies=[Depends(authorize)])
    async def usage():
        watches = await store().list_active(owner())
        normal = sum(24 / max(watch.interval_hours, 1) for watch in watches)
        weekly = normal * 7 + sum(6 for watch in watches if watch.weekly_flex)
        return {"used_today": await store().usage_today(), "daily_cap": settings.watch_daily_token_cap,
                "active": len(watches), "active_cap": settings.watch_max_active,
                "projected_daily": normal, "projected_weekly": weekly}

    @app.get("/api/v1/deals", dependencies=[Depends(authorize)])
    async def deals():
        watches = [watch for watch in await store().list_active(owner()) if watch.last_price is not None]
        watches.sort(key=lambda watch: min(
            watch.last_price / watch.target_price if watch.target_price else 99,
            watch.last_price / watch.record_low if watch.record_low else 99,
        ))
        return [_watch_json(watch) for watch in watches]

    @app.get("/api/v1/cleanup", dependencies=[Depends(authorize)])
    async def cleanup():
        watches = await store().list_active(owner())
        return [_watch_json(watch) for watch in watches
                if watch.consecutive_failures >= 3 or watch.request.departure_date <= date.today()]

    @app.get("/api/v1/export", dependencies=[Depends(authorize)])
    async def export():
        return await store().export_user_data(owner())

    return app
