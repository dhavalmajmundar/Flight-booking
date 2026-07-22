from __future__ import annotations

import logging
import math
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from .config import Settings
from .command_input import command_arguments
from .links import expedia_search_url, google_flights_url, kayak_search_url
from .models import Cabin, FlightOption, Priority, SearchRequest
from .ranking import itinerary_risks, observed_deal_label, rank_flights
from .routestack import FlightSearchError, RouteStackClient
from .watch_store import Watch, WatchStore

logger = logging.getLogger(__name__)

WATCH_CONFIRM = 200


@dataclass
class PendingWatch:
    request: SearchRequest
    target_price: float | None
    drop_percent: float
    interval_hours: int
    expires_at: datetime
    maximum_checks: int


def _future_date(value: str, today: date | None = None) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("dates must use YYYY-MM-DD") from exc
    if parsed < (today or date.today()):
        raise ValueError("travel dates must be in the future")
    return parsed


def _airline_codes(value: str) -> set[str]:
    codes = {item.strip().upper() for item in value.split(",") if item.strip()}
    if any(not re.fullmatch(r"[A-Z0-9]{2}", code) for code in codes):
        raise ValueError("airlines must use 2-character IATA codes")
    return codes


def parse_watch_command(
    args: list[str], settings: Settings, now: datetime | None = None
) -> PendingWatch:
    if len(args) < 3:
        raise ValueError("origin, destination, and departure date are required")
    now = now or datetime.now(timezone.utc)
    departure = _future_date(args[2], now.date())
    returning = departure + timedelta(days=7)
    adults = 4
    cabin = Cabin.ECONOMY
    target: float | None = None
    drop_percent = 5.0
    interval_hours = 24
    duration_days = settings.watch_max_days
    preferred: set[str] = set()
    avoided: set[str] = set()
    checked_bags = 2
    carry_on_bags = 1
    auto_baggage = False

    allowed = {
        "--return",
        "--trip",
        "--target",
        "--drop",
        "--every",
        "--for-days",
        "--adults",
        "--cabin",
        "--prefer",
        "--avoid",
        "--bags",
        "--carry-on",
    }
    index = 3
    while index < len(args):
        option = args[index].lower()
        if option not in allowed:
            raise ValueError(f"unknown option: {args[index]}")
        if index + 1 >= len(args):
            raise ValueError(f"{option} requires a value")
        value = args[index + 1]
        if option == "--return":
            returning = _future_date(value, now.date())
            if returning <= departure:
                raise ValueError("--return must be after departure")
        elif option == "--trip":
            normalized_trip = value.lower().replace("_", "-")
            if normalized_trip in {"one-way", "oneway"}:
                returning = None
            elif normalized_trip in {"round-trip", "roundtrip"}:
                returning = returning or departure + timedelta(days=7)
            else:
                raise ValueError("--trip must be one-way or round-trip")
        elif option == "--target":
            try:
                target = float(value.replace("$", "").replace(",", ""))
            except ValueError as exc:
                raise ValueError("--target must be a positive number") from exc
            if target <= 0:
                raise ValueError("--target must be a positive number")
        elif option == "--drop":
            try:
                drop_percent = float(value.replace("%", ""))
            except ValueError as exc:
                raise ValueError("--drop must be from 1 to 50") from exc
            if not 1 <= drop_percent <= 50:
                raise ValueError("--drop must be from 1 to 50")
        elif option == "--every":
            try:
                interval_hours = int(value.lower().replace("h", ""))
            except ValueError as exc:
                raise ValueError("--every must be 6, 12, 24, or 48 hours") from exc
            if interval_hours not in {6, 12, 24, 48}:
                raise ValueError("--every must be 6, 12, 24, or 48 hours")
        elif option == "--for-days":
            try:
                duration_days = int(value)
            except ValueError as exc:
                raise ValueError(
                    f"--for-days must be from 1 to {settings.watch_max_days}"
                ) from exc
            if not 1 <= duration_days <= settings.watch_max_days:
                raise ValueError(
                    f"--for-days must be from 1 to {settings.watch_max_days}"
                )
        elif option == "--adults":
            try:
                adults = int(value)
            except ValueError as exc:
                raise ValueError("--adults must be from 1 to 6") from exc
            if not 1 <= adults <= 6:
                raise ValueError("--adults must be from 1 to 6")
        elif option == "--cabin":
            normalized = value.upper().replace("-", "_")
            try:
                cabin = Cabin(normalized)
            except ValueError as exc:
                raise ValueError(
                    "--cabin must be economy, premium-economy, business, or first"
                ) from exc
        elif option == "--prefer":
            preferred = _airline_codes(value)
        elif option == "--avoid":
            avoided = _airline_codes(value)
        elif option == "--bags":
            if value.lower() == "auto":
                auto_baggage = True
            else:
                try:
                    checked_bags = int(value)
                except ValueError as exc:
                    raise ValueError("--bags must be 0, 1, 2, or auto") from exc
                if checked_bags not in {0, 1, 2}:
                    raise ValueError("--bags must be 0, 1, 2, or auto")
                auto_baggage = False
        elif option == "--carry-on":
            try:
                carry_on_bags = int(value)
            except ValueError as exc:
                raise ValueError("--carry-on must be 0, 1, or 2") from exc
            if carry_on_bags not in {0, 1, 2}:
                raise ValueError("--carry-on must be 0, 1, or 2")
        index += 2

    departure_cutoff = datetime.combine(
        departure, time(hour=0), tzinfo=timezone.utc
    ) - timedelta(hours=12)
    expires_at = min(now + timedelta(days=duration_days), departure_cutoff)
    if expires_at <= now:
        raise ValueError("the departure is too soon to create a watch")
    maximum_checks = max(
        1,
        math.ceil(
            (expires_at - now).total_seconds()
            / (min(interval_hours, 6) * 3600)
        ),
    )
    request = SearchRequest(
        origin=args[0].strip().replace("_", " "),
        destination=args[1].strip().replace("_", " "),
        departure_date=departure,
        return_date=returning,
        adults=adults,
        cabin=cabin,
        flexible_dates=False,
        flexible_days=0,
        nearby_airports=False,
        checked_bags=checked_bags,
        carry_on_bags=carry_on_bags,
        auto_baggage=auto_baggage,
        auto_nearby=False,
        preferred_airlines=preferred,
        avoided_airlines=avoided,
        priority=Priority.CHEAPEST,
        currency=settings.default_currency,
    )
    return PendingWatch(
        request=request,
        target_price=target,
        drop_percent=drop_percent,
        interval_hours=interval_hours,
        expires_at=expires_at,
        maximum_checks=maximum_checks,
    )


def observed_price_guidance(prices: list[float]) -> str:
    if not prices:
        return "No observed history yet."
    if len(prices) == 1:
        return "Baseline recorded; more checks are needed for a trend."
    current = prices[-1]
    record_low = min(prices)
    if current <= record_low:
        return "Book-now candidate: this is the lowest price observed by this watch."
    if current <= record_low * 1.02:
        return "Good observed price: within 2% of this watch's record low."
    if len(prices) >= 3 and prices[-1] > prices[-2] > prices[-3]:
        return "Consider booking: the last three observed prices increased."
    return "Wait/watch: the current price is above this watch's observed low."


def adaptive_watch_interval_hours(
    watch: Watch, now: datetime | None = None
) -> int:
    """Use scarce watch calls more often only as urgency increases."""
    now = now or datetime.now(timezone.utc)
    days_until_departure = (watch.request.departure_date - now.date()).days
    interval = watch.interval_hours
    if days_until_departure > 90:
        interval = max(interval, 48)
    elif days_until_departure > 30:
        interval = max(interval, 24)
    elif days_until_departure <= 3:
        interval = min(interval, 6)
    elif days_until_departure <= 14:
        interval = min(interval, 12)
    if (
        watch.target_price is not None
        and watch.last_price is not None
        and watch.last_price <= watch.target_price * 1.05
    ):
        interval = min(interval, 12)
    return min((6, 12, 24, 48), key=lambda value: abs(value - interval))


def watch_urgency_key(
    watch: Watch, now: datetime | None = None
) -> tuple[float, int, datetime]:
    now = now or datetime.now(timezone.utc)
    days = max(0, (watch.request.departure_date - now.date()).days)
    target_component = 2.5
    if (
        watch.target_price is not None
        and watch.last_price is not None
        and watch.target_price > 0
    ):
        target_gap = abs(watch.last_price - watch.target_price) / watch.target_price
        target_component = min(target_gap * 10, 5)
    urgency_score = min(days / 30, 5) + target_component
    return urgency_score, days, watch.next_check_at


def _store(application) -> WatchStore | None:
    return application.bot_data.get("watch_store")


async def watch_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    store = _store(context.application)
    settings: Settings = context.application.bot_data["settings"]
    if not store:
        await update.message.reply_text(
            "Price watches are disabled until Railway Postgres supplies DATABASE_URL."
        )
        return ConversationHandler.END
    if await store.count_active(update.effective_user.id) >= settings.watch_max_active:
        await update.message.reply_text(
            f"You already have {settings.watch_max_active} active watches. "
            "Use /watches and /unwatch first."
        )
        return ConversationHandler.END
    try:
        args = command_arguments(update.message.text, context.args)
        pending = parse_watch_command(args, settings)
    except ValueError as exc:
        await update.message.reply_text(
            f"Invalid watch: {exc}\n\n"
            "Example:\n"
            "/watch JFK LAX 2026-09-15 --return 2026-09-22 "
            "--target 350 --drop 5 --every 24 --for-days 30"
        )
        return ConversationHandler.END
    context.user_data["pending_watch"] = pending
    target = (
        f"{pending.request.currency} {pending.target_price:,.2f}"
        if pending.target_price
        else "new record low"
    )
    await update.message.reply_text(
        "Activate this price watch?\n"
        f"{pending.request.origin} → {pending.request.destination}\n"
        f"{pending.request.departure_date} → {pending.request.return_date}\n"
        f"{pending.request.adults} adult(s), {pending.request.cabin.value}\n"
        f"Baggage: "
        f"{'smart checked bags' if pending.request.auto_baggage else str(pending.request.checked_bags) + ' checked'}"
        f" + {pending.request.carry_on_bags} carry-on per traveler\n"
        f"Alert target: {target}; drop threshold: {pending.drop_percent:g}%\n"
        f"Check every {pending.interval_hours}h; expires "
        f"{pending.expires_at:%Y-%m-%d}\n\n"
        "Each check searches one exact route/date with flexible dates and nearby "
        "airports off. It uses at most 1 RouteStack token. Estimated maximum: "
        f"{pending.maximum_checks} token(s). Daily global cap applies. The scheduler "
        "automatically checks less often far from departure and prioritizes trips "
        "near departure or near their target price.\n\n"
        "Send Activate watch or Cancel.",
    )
    return WATCH_CONFIRM


async def activate_watch(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    answer = update.message.text.strip().lower()
    if answer == "cancel":
        context.user_data.pop("pending_watch", None)
        await update.message.reply_text("Watch creation cancelled. No token was used.")
        return ConversationHandler.END
    if answer != "activate watch":
        await update.message.reply_text("Send Activate watch or Cancel.")
        return WATCH_CONFIRM
    pending: PendingWatch | None = context.user_data.pop("pending_watch", None)
    store = _store(context.application)
    if not pending or not store:
        await update.message.reply_text("That watch request expired. Use /watch again.")
        return ConversationHandler.END
    watch = await store.create_watch(
        update.effective_user.id,
        pending.request,
        pending.target_price,
        pending.drop_percent,
        pending.interval_hours,
        pending.expires_at,
    )
    await update.message.reply_text(
        f"Watch {watch.short_id} activated. Its baseline check is queued and "
        "will respect the daily token cap.\n"
        "Use /watches, /history "
        f"{watch.short_id}, /checknow {watch.short_id}, or "
        f"/unwatch {watch.short_id}."
    )
    return ConversationHandler.END


async def watches_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    store = _store(context.application)
    if not store:
        await update.message.reply_text("Price watches are not configured.")
        return
    watches = await store.list_active(update.effective_user.id)
    if not watches:
        await update.message.reply_text("You have no active watches. Use /watch.")
        return
    lines = ["Active price watches:"]
    for watch in watches:
        price = (
            f"{watch.request.currency} {watch.last_price:,.2f}"
            if watch.last_price is not None
            else "awaiting baseline"
        )
        lines.append(
            f"• {watch.short_id}: {watch.request.origin} → "
            f"{watch.request.destination}, {watch.request.departure_date}, "
            f"last {price}, every {watch.interval_hours}h, "
            f"expires {watch.expires_at:%Y-%m-%d}"
        )
    await update.message.reply_text("\n".join(lines))


async def unwatch_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.args:
        await update.message.reply_text("Use /unwatch WATCH_ID")
        return
    store = _store(context.application)
    if not store:
        await update.message.reply_text("Price watches are not configured.")
        return
    removed = await store.deactivate(update.effective_user.id, context.args[0])
    await update.message.reply_text(
        "Watch stopped." if removed else "No matching active watch was found."
    )


async def checknow_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.args:
        await update.message.reply_text("Use /checknow WATCH_ID")
        return
    store = _store(context.application)
    settings: Settings = context.application.bot_data["settings"]
    if not store:
        await update.message.reply_text("Price watches are not configured.")
        return
    if await store.usage_today() >= settings.watch_daily_token_cap:
        await update.message.reply_text(
            "The daily watch-token cap has been reached. No search was queued."
        )
        return
    scheduled = await store.schedule_now(
        update.effective_user.id, context.args[0]
    )
    await update.message.reply_text(
        "One exact-date check was queued and may use 1 RouteStack token."
        if scheduled
        else "No matching active watch was found."
    )


async def history_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.args:
        await update.message.reply_text("Use /history WATCH_ID")
        return
    store = _store(context.application)
    if not store:
        await update.message.reply_text("Price watches are not configured.")
        return
    watch = await store.get_by_prefix(update.effective_user.id, context.args[0])
    if not watch:
        await update.message.reply_text("No unique active watch matched that ID.")
        return
    history = await store.recent_prices(watch.id, days=60)
    if not history:
        await update.message.reply_text("This watch has no price history yet.")
        return
    values = [price for _, price in history]
    recent = history[-10:]
    lines = [
        f"Price history for {watch.short_id} "
        f"({watch.request.origin} → {watch.request.destination}):"
    ]
    lines.extend(
        f"• {checked:%Y-%m-%d %H:%M} UTC: "
        f"{watch.request.currency} {price:,.2f}"
        for checked, price in recent
    )
    lines.append(observed_price_guidance(values))
    await update.message.reply_text("\n".join(lines))


async def usage_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    store = _store(context.application)
    settings: Settings = context.application.bot_data["settings"]
    if not store:
        await update.message.reply_text("Price watches are not configured.")
        return
    used = await store.usage_today()
    active = await store.count_active(update.effective_user.id)
    await update.message.reply_text(
        f"Watch tokens attempted today: {used}/"
        f"{settings.watch_daily_token_cap}\n"
        f"Active watches: {active}/{settings.watch_max_active}\n"
        "Checks pause automatically when the daily cap is reached."
    )


def _alert_reasons(watch: Watch, price: float) -> list[str]:
    if watch.last_price is None:
        reasons = ["baseline price recorded"]
        if watch.target_price is not None and price <= watch.target_price:
            reasons.append("target price reached")
        return reasons
    reasons: list[str] = []
    if (
        watch.target_price is not None
        and price <= watch.target_price
        and watch.last_price > watch.target_price
    ):
        reasons.append("target price reached")
    drop = (watch.last_price - price) / watch.last_price * 100
    if drop >= watch.drop_percent:
        reasons.append(f"price dropped {drop:.1f}%")
    if watch.record_low is None or price < watch.record_low:
        reasons.append("new record low")
    if (
        watch.last_alert_price is not None
        and abs(price - watch.last_alert_price) < 0.005
    ):
        return []
    return reasons


def _watch_buttons(application, user_id: int, option: FlightOption, request: SearchRequest):
    token = secrets.token_urlsafe(6)
    user_data = application.user_data[user_id]
    handoffs = user_data.setdefault("booking_handoffs", {})
    handoffs[token] = {"request": request, "options": [option]}
    while len(handoffs) > 3:
        handoffs.pop(next(iter(handoffs)))
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Open exact fare",
                    callback_data=f"checkout:{token}:0",
                )
            ],
            [
                InlineKeyboardButton(
                    "Compare on Expedia",
                    url=expedia_search_url(option, request),
                ),
                InlineKeyboardButton(
                    "Google Flights",
                    url=google_flights_url(option, request),
                ),
            ],
            [
                InlineKeyboardButton(
                    "Compare on Kayak",
                    url=kayak_search_url(option, request),
                )
            ],
        ]
    )


async def _send_watch_alert(
    application,
    watch: Watch,
    option: FlightOption,
    reasons: list[str],
    history: list[tuple[datetime, float]],
) -> None:
    previous = (
        f"{option.currency} {watch.last_price:,.2f}"
        if watch.last_price is not None
        else "none"
    )
    guidance = observed_price_guidance(
        [price for _, price in history] + [option.total_price]
    )
    deal_level = observed_deal_label(
        option.total_price, [price for _, price in history]
    )
    risks = itinerary_risks(option)
    risk_text = (
        "\n🚨 Important itinerary warning: " + "; ".join(risks)
        if risks
        else ""
    )
    await application.bot.send_message(
        chat_id=watch.user_id,
        text=(
            f"🔔 Watch {watch.short_id}: {', '.join(reasons)}\n"
            f"{watch.request.origin} → {watch.request.destination}\n"
            f"Travel: {watch.request.departure_date} → "
            f"{watch.request.return_date}\n"
            f"Current: {option.currency} {option.total_price:,.2f}\n"
            f"Previous: {previous}\n"
            f"Airline: {', '.join(option.airlines)} | "
            f"{option.duration_minutes // 60}h "
            f"{option.duration_minutes % 60:02d}m | "
            f"{'nonstop' if option.stops == 0 else f'{option.stops} stop(s)'}\n"
            f"Observed deal level: {deal_level}\n"
            f"{guidance}{risk_text}\n\n"
            "Prices can change. The exact link revalidates before checkout."
        ),
        reply_markup=_watch_buttons(
            application, watch.user_id, option, watch.request
        ),
    )


async def _check_watch(
    application, store: WatchStore, watch: Watch
) -> None:
    interval = adaptive_watch_interval_hours(watch)
    if not await store.claim(watch, interval):
        return
    await store.increment_usage()
    client: RouteStackClient = application.bot_data["routestack"]
    try:
        offers, _, _ = await client.search(watch.request)
        results = rank_flights(offers, watch.request)
        if not results:
            await store.record_failure(watch.id)
            return
        option = results.cheapest
        history = await store.recent_prices(watch.id, days=60)
        previous_observation = await store.latest_observation(watch.id)
        reasons = _alert_reasons(watch, option.total_price)
        if (
            previous_observation
            and previous_observation[2] is not None
            and previous_observation[2] > 0
            and option.stops == 0
        ):
            if (
                watch.target_price is not None
                and option.total_price <= watch.target_price
            ):
                reasons.append("nonstop option is now affordable")
            elif watch.target_price is None:
                reasons.append("nonstop option is now the cheapest observed itinerary")
        if previous_observation and reasons:
            _, previous_duration, previous_stops = previous_observation
            if (
                previous_stops is not None
                and option.stops > previous_stops
            ):
                reasons.append(
                    f"tradeoff: now has {option.stops} stop(s), previously "
                    f"{previous_stops}"
                )
            if (
                previous_duration is not None
                and option.duration_minutes > previous_duration + 120
            ):
                reasons.append(
                    "tradeoff: itinerary is over 2 hours longer than the "
                    "previous observed option"
                )
        alert_sent = False
        if reasons:
            try:
                await _send_watch_alert(
                    application, watch, option, reasons, history
                )
                alert_sent = True
            except TelegramError as exc:
                logger.warning(
                    "Could not deliver watch %s alert: %s",
                    watch.short_id,
                    exc,
                )
        await store.record_success(
            watch,
            option.total_price,
            option.currency,
            ", ".join(option.airlines),
            option.duration_minutes,
            option.stops,
            alert_sent,
        )
    except FlightSearchError as exc:
        logger.warning("Watch %s search failed: %s", watch.short_id, exc)
        await store.record_failure(watch.id)
    except Exception:
        logger.exception("Unexpected watch %s failure", watch.short_id)
        await store.record_failure(watch.id)


async def _send_digest_and_reminders(application, store: WatchStore) -> None:
    settings: Settings = application.bot_data["settings"]
    owner = settings.owner_telegram_user_id
    if owner is None:
        return
    now = datetime.now(timezone.utc)
    today = now.date()
    watches = await store.list_active(owner)
    for watch in await store.expiring_watches(owner):
        if watch.last_price is not None:
            reminder = (
                f"⏳ Watch {watch.short_id} expires within 48 hours. "
                f"Last observed price: {watch.request.currency} "
                f"{watch.last_price:,.2f}"
            )
        else:
            reminder = f"⏳ Watch {watch.short_id} expires within 48 hours."
        await application.bot.send_message(
            owner,
            reminder,
        )
        await store.mark_expiry_reminded(watch.id)

    if (
        watches
        and now.hour >= settings.watch_digest_hour_utc
        and await store.notification_due(owner, "daily_digest", today)
    ):
        priced = [watch for watch in watches if watch.last_price is not None]
        if priced:
            lines = ["☀️ Daily flight-watch digest"]
            lines.extend(
                f"• {watch.short_id} {watch.request.origin}→"
                f"{watch.request.destination}: {watch.request.currency} "
                f"{watch.last_price:,.2f}"
                for watch in priced
            )
            lines.append(
                f"Watch tokens used today: {await store.usage_today()}/"
                f"{settings.watch_daily_token_cap}"
            )
            await application.bot.send_message(owner, "\n".join(lines))
        await store.mark_notification(owner, "daily_digest", today)

    if (
        watches
        and now.weekday() == 0
        and now.hour >= settings.watch_digest_hour_utc
        and await store.notification_due(owner, "weekly_summary", today)
    ):
        lines = ["📈 Weekly flight-watch summary"]
        for watch in watches:
            history = await store.recent_prices(watch.id, days=7)
            if not history:
                continue
            values = [price for _, price in history]
            lines.append(
                f"• {watch.short_id} {watch.request.origin}→"
                f"{watch.request.destination}: low "
                f"{watch.request.currency} {min(values):,.2f}, high "
                f"{watch.request.currency} {max(values):,.2f}, "
                f"current {watch.request.currency} {values[-1]:,.2f}. "
                f"{observed_price_guidance(values)}"
            )
        if len(lines) > 1:
            await application.bot.send_message(owner, "\n".join(lines))
        await store.mark_notification(owner, "weekly_summary", today)


async def run_watch_cycle(context: ContextTypes.DEFAULT_TYPE) -> None:
    application = context.application
    store = _store(application)
    settings: Settings = application.bot_data["settings"]
    if not store or settings.owner_telegram_user_id is None:
        return
    await store.expire_old()
    due = await store.due_watches(limit=max(settings.watch_daily_token_cap, 25))
    due.sort(key=watch_urgency_key)
    for watch in due:
        if await store.usage_today() >= settings.watch_daily_token_cap:
            await store.postpone_due_until_tomorrow()
            today = datetime.now(timezone.utc).date()
            owner = settings.owner_telegram_user_id
            if await store.notification_due(owner, "daily_cap", today):
                await application.bot.send_message(
                    owner,
                    f"⏸ Daily watch-token cap "
                    f"({settings.watch_daily_token_cap}) reached. Remaining "
                    "checks are paused until tomorrow.",
                )
                await store.mark_notification(owner, "daily_cap", today)
            break
        await _check_watch(application, store, watch)
    await _send_digest_and_reminders(application, store)
