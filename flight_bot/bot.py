from __future__ import annotations

import calendar
import logging
import re
import secrets
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from .config import Settings
from .airports import (
    is_domestic,
    local_airport,
    local_airport_suggestions,
)
from .command_input import command_arguments
from .formatting import format_results, selected_results
from .links import expedia_search_url, google_flights_url, kayak_search_url
from .models import Cabin, DepartureWindow, FlightOption, Priority, SearchRequest
from .ranking import itinerary_risks, rank_flights
from .routestack import FlightSearchError, RouteStackClient
from .watch_store import UserProfile, WatchStore
from .watching import (
    WATCH_CONFIRM,
    WATCH_ORIGIN, WATCH_DESTINATION, WATCH_DEPARTURE, WATCH_TRIP,
    WATCH_DURATION, WATCH_TARGET, WATCH_DROP, WATCH_INTERVAL,
    WATCH_DAYS, WATCH_WEEKLY,
    activate_watch,
    booked_callback,
    booked_command,
    chart_command,
    checknow_command,
    cleanup_command,
    deals_command,
    export_command,
    health_command,
    history_command,
    run_watch_cycle,
    unwatch_command,
    usage_command,
    watch_date_callback,
    watch_command,
    watch_days,
    watch_departure,
    watch_destination,
    watch_drop,
    watch_duration,
    watch_interval,
    watch_origin,
    watch_target,
    watch_trip,
    watch_weekly,
    watches_command,
)

logger = logging.getLogger(__name__)

(
    ORIGIN,
    DESTINATION,
    DEPARTURE,
    TRIP_TYPE,
    RETURN,
    PASSENGERS,
    CABIN,
    CURRENCY,
    TIME_PREF,
    MAX_STOPS,
    RED_EYE,
    CONNECTION,
    DURATION_LIMIT,
    FLEXIBLE,
    FLEX_DAYS,
    NEARBY,
    BAGS,
    CARRY_ON,
    AIRLINES,
    BUDGET,
    PRIORITY,
    CONFIRM,
) = range(22)


def _keyboard(*rows: tuple[str, ...]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def _default_choice(label: str, selected: bool) -> str:
    return f"{label} (default)" if selected else label


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "I search and compare live flights only when you request one.\n\n"
        "Use /search for a guided search, /flight for one line, /watch for a "
        "private price alert, or /help for details."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Use /search and answer the guided questions. I will collect your route, "
        "start date, duration, trip type, passengers, flexibility, nearby-airport "
        "choice, cabin, baggage, airline preferences, budget, and priority. The "
        "calendar and choice buttons mean only the route normally needs typing. "
        "No provider search happens until you confirm.\n\n"
        "Use /defaults to review the smart settings without making a search.\n\n"
        "Price-watch commands:\n"
        "/watch — button-driven setup (recommended)\n"
        "/watch JFK LAX 2026-09-15 --return 2026-09-22 --target 350 "
        "--drop 5 --every 24 --for-days 30\n"
        "/watches — list alerts\n"
        "/history WATCH_ID — observed prices and guidance\n"
        "/checknow WATCH_ID — queue one token-capped check\n"
        "/unwatch WATCH_ID — stop an alert\n"
        "/usage — today's watch-token usage\n\n"
        "/deals — rank active watches using stored prices\n"
        "/chart WATCH_ID — no-token price trend\n"
        "/booked WATCH_ID — mark purchased and stop\n"
        "/cleanup — find stale watches\n"
        "/health — owner-only service diagnostics\n"
        "/export — private JSON backup\n\n"
        "Free helpers (no RouteStack search token):\n"
        "/airports New York, NY — local airport-code suggestions\n"
        "/recent — recent successful searches\n"
        "/repeat 1 — review and confirm a recent search\n"
        "/profile — saved airline, budget, and layover preferences\n\n"
        "For a one-line request:\n"
        "/flight JFK LAX 2026-09-15\n\n"
        "Natural-language shortcut (uses saved/default preferences):\n"
        "/quick New York to Paris on October 10, 2026 for 8 days\n\n"
        "For cities with spaces:\n"
        "/flight New York, NY | Los Angeles, CA | 2026-09-15\n\n"
        "Smart defaults: round trip returning after 7 nights, 4 adults, economy, "
        "flexible dates, nearby airports for domestic trips only, and automatic "
        "baggage (2 checked + 1 carry-on by default).\n\n"
        "Override with options such as --return 2026-09-20 --nights 5 "
        "--trip one-way --adults 2 --cabin business --flex no --nearby yes "
        "--bags 1 --carry-on 1 --prefer DL,UA --avoid NK,F9 --budget 1200 "
        "--priority balanced --max-layover 240 --flex-days 3\n\n"
        "Comfort overrides: --currency USD --time morning --max-stops 1 "
        "--red-eye avoid --min-layover 60 --max-duration 24h. These helpers "
        "rank and warn locally; they do not make extra provider calls.\n\n"
        "RouteStack does not currently document dependable search inputs for "
        "children/infants, multi-city, seat maps, or complete fare rules, so the "
        "bot does not pretend those are supported. Verify fare rules and seats "
        "during checkout.\n\n"
        "Smart progressive search tries one suggested date first, expands to "
        "±3 days only when needed, then checks eligible domestic nearby airports "
        "only if results remain missing or risky. The confirmation always shows "
        "the maximum possible search-token use.\n\n"
        "Airport codes such as JFK work best, but city or airport names are accepted."
    )


async def defaults_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.message.reply_text(
        "Smart defaults for /flight:\n"
        "• Round trip returning 7 days later\n"
        "• 4 adults in Economy\n"
        "• Flexible dates within ±3 days\n"
        "• Nearby airports: on domestic, off international\n"
        "• Baggage: 2 checked + 1 carry-on per traveler\n"
        "• Optional Smart checked-bag mode: 0 domestic, 2 international\n"
        "• USD and any departure time / number of stops\n"
        "• Avoid red-eyes; standard 1–5 hour connections\n"
        "• No maximum itinerary duration\n"
        "• Balanced ranking\n\n"
        "Before searching, choose smart progressive search, the free suggested-date "
        "estimate, or the full live ±3-day comparison. Risky itineraries remain "
        "visible but receive prominent warnings and a ranking penalty. Use /help "
        "for every one-line override."
    )


BOT_COMMANDS = (
    BotCommand("start", "Open the flight assistant"),
    BotCommand("search", "Start a guided flight search"),
    BotCommand("flight", "Search in one line: JFK LAX 2026-09-15"),
    BotCommand("quick", "Natural request: New York to Paris..."),
    BotCommand("watch", "Create a recurring price alert"),
    BotCommand("watches", "List active price watches"),
    BotCommand("history", "Show observed watch prices"),
    BotCommand("checknow", "Queue one watch check"),
    BotCommand("usage", "Show today's watch token usage"),
    BotCommand("unwatch", "Stop a price watch"),
    BotCommand("deals", "Rank active stored deals"),
    BotCommand("chart", "Show a watch price chart"),
    BotCommand("booked", "Mark a watch purchased and stop it"),
    BotCommand("cleanup", "Find stale watches"),
    BotCommand("health", "Check bot and database health"),
    BotCommand("export", "Export private watch data"),
    BotCommand("airports", "Find airport codes locally"),
    BotCommand("recent", "Show recent successful searches"),
    BotCommand("repeat", "Repeat a recent search"),
    BotCommand("profile", "View or update saved preferences"),
    BotCommand("defaults", "Show smart search defaults"),
    BotCommand("help", "Show commands and one-line options"),
    BotCommand("cancel", "Cancel the current search"),
    BotCommand("myid", "Show your Telegram user ID"),
)


async def configure_bot_commands(application: Application) -> None:
    try:
        await application.bot.set_my_commands(BOT_COMMANDS)
        logger.info("Registered %d Telegram bot commands", len(BOT_COMMANDS))
    except TelegramError as exc:
        # A temporary Telegram failure should not stop polling or flight search.
        logger.warning("Could not register Telegram command menu: %s", exc)


async def access_gate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Stop unauthorized updates before they can reach any provider handler."""
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.effective_message
    text = (message.text or "").strip().lower() if message else ""
    if text.startswith("/myid") and (
        settings.owner_telegram_user_id is None
        or (
            user is not None
            and user.id == settings.owner_telegram_user_id
        )
    ):
        if message and user:
            await message.reply_text(
                f"Your Telegram user ID is: {user.id}\n"
                "Set Railway OWNER_TELEGRAM_USER_ID to this number."
            )
        raise ApplicationHandlerStop

    authorized = bool(
        user
        and settings.owner_telegram_user_id is not None
        and user.id == settings.owner_telegram_user_id
    )
    if authorized:
        return

    if update.callback_query:
        await update.callback_query.answer(
            "This private bot is restricted to its owner.", show_alert=True
        )
    elif message:
        if settings.owner_telegram_user_id is None:
            await message.reply_text(
                "This private bot is locked until its owner is configured. "
                "Send /myid to obtain your Telegram ID."
            )
        else:
            await message.reply_text("This is a private bot.")
    logger.warning("Blocked an unauthorized Telegram update")
    raise ApplicationHandlerStop


async def on_startup(application: Application) -> None:
    await configure_bot_commands(application)
    store: WatchStore | None = application.bot_data.get("watch_store")
    if not store:
        logger.warning(
            "DATABASE_URL is not configured; persistent price watches are disabled."
        )
        return
    try:
        await store.initialize()
    except Exception:
        logger.exception("Could not initialize the watch database; watches disabled")
        application.bot_data.pop("watch_store", None)
        return
    if application.job_queue:
        application.job_queue.run_repeating(
            run_watch_cycle,
            interval=300,
            first=15,
            name="flight-price-watch-cycle",
        )
        logger.info("Persistent flight price watcher scheduled")


async def begin_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["trip"] = {
        "adults": 4,
        "cabin": Cabin.ECONOMY,
        "currency": context.application.bot_data["settings"].default_currency,
        "checked_bags": 2,
        "carry_on_bags": 1,
        "departure_window": DepartureWindow.ANY,
        "avoid_red_eye": True,
        "max_stops": None,
        "min_layover_minutes": 60,
        "max_layover_minutes": 300,
        "max_total_duration_minutes": None,
    }
    store: WatchStore | None = context.application.bot_data.get("watch_store")
    if store and update.effective_user:
        try:
            profile = await store.get_profile(update.effective_user.id)
            context.user_data["trip"].update(
                adults=profile.adults,
                cabin=profile.cabin,
                currency=profile.currency,
                checked_bags=profile.checked_bags,
                carry_on_bags=profile.carry_on_bags,
                departure_window=profile.departure_window,
                avoid_red_eye=profile.avoid_red_eye,
                max_stops=profile.max_stops,
                min_layover_minutes=profile.min_layover_minutes,
                max_layover_minutes=profile.max_layover_minutes,
                max_total_duration_minutes=profile.max_total_duration_minutes,
                preferred_airlines=set(profile.preferred_airlines),
                avoided_airlines=set(profile.avoided_airlines),
                max_budget=profile.max_budget,
            )
        except Exception:
            logger.exception("Could not load guided-search profile defaults")
    await update.message.reply_text(
        "Where are you departing from? Send a city, airport, or 3-letter code.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ORIGIN


def _yes_no(value: str, option: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"yes", "no"}:
        raise ValueError(f"{option} must be yes or no")
    return normalized == "yes"


def _airline_codes(value: str, option: str) -> set[str]:
    codes = {code.strip().upper() for code in value.split(",") if code.strip()}
    if any(not re.fullmatch(r"[A-Z0-9]{2}", code) for code in codes):
        raise ValueError(f"{option} must contain 2-character IATA airline codes")
    return codes


def parse_flight_command(args: list[str]) -> dict:
    if len(args) < 3:
        raise ValueError("origin, destination, and departure date are required")

    departure_value = _parse_future_date(args[2])
    if not departure_value:
        raise ValueError("departure must be a future date in YYYY-MM-DD format")

    trip: dict = {
        "origin": args[0].strip().replace("_", " "),
        "destination": args[1].strip().replace("_", " "),
        "departure_date": departure_value,
        "return_date": departure_value + timedelta(days=7),
        "adults": 4,
        "cabin": Cabin.ECONOMY,
        "flexible_dates": True,
        "flexible_days": 3,
        "nearby_airports": False,
        "auto_nearby": True,
        "checked_bags": 2,
        "carry_on_bags": 1,
        "auto_baggage": False,
        "preferred_airlines": set(),
        "avoided_airlines": set(),
        "max_budget": None,
        "priority": Priority.BALANCED,
        "max_layover_minutes": 300,
        "min_layover_minutes": 60,
        "departure_window": DepartureWindow.ANY,
        "avoid_red_eye": True,
        "max_stops": None,
        "max_total_duration_minutes": None,
        "currency": "USD",
    }
    value_options = {
        "--return",
        "--nights",
        "--trip",
        "--adults",
        "--cabin",
        "--flex",
        "--flex-days",
        "--nearby",
        "--bags",
        "--carry-on",
        "--prefer",
        "--avoid",
        "--budget",
        "--priority",
        "--max-layover",
        "--min-layover",
        "--time",
        "--red-eye",
        "--max-stops",
        "--max-duration",
        "--currency",
    }
    index = 3
    while index < len(args):
        option = args[index].lower()
        if option not in value_options:
            raise ValueError(f"unknown option: {args[index]}")
        if index + 1 >= len(args):
            raise ValueError(f"{option} requires a value")
        value = args[index + 1]

        if option == "--return":
            parsed = _parse_future_date(value)
            if not parsed or parsed <= trip["departure_date"]:
                raise ValueError("--return must be after departure")
            trip["return_date"] = parsed
        elif option == "--nights":
            try:
                nights = int(value)
            except ValueError as exc:
                raise ValueError("--nights must be a number from 1 to 365") from exc
            if not 1 <= nights <= 365:
                raise ValueError("--nights must be a number from 1 to 365")
            trip["return_date"] = trip["departure_date"] + timedelta(days=nights)
        elif option == "--trip":
            trip_type = value.lower().replace("_", "-")
            if trip_type in {"one-way", "oneway"}:
                trip["return_date"] = None
            elif trip_type in {"round-trip", "roundtrip"}:
                trip["return_date"] = (
                    trip["return_date"]
                    or trip["departure_date"] + timedelta(days=7)
                )
            else:
                raise ValueError("--trip must be one-way or round-trip")
        elif option == "--adults":
            try:
                adults = int(value)
            except ValueError as exc:
                raise ValueError("--adults must be a number from 1 to 9") from exc
            if not 1 <= adults <= 9:
                raise ValueError("--adults must be a number from 1 to 9")
            trip["adults"] = adults
        elif option == "--cabin":
            cabin_value = value.lower().replace("-", "_")
            cabin_map = {
                "economy": Cabin.ECONOMY,
                "premium_economy": Cabin.PREMIUM_ECONOMY,
                "business": Cabin.BUSINESS,
                "first": Cabin.FIRST,
            }
            if cabin_value not in cabin_map:
                raise ValueError(
                    "--cabin must be economy, premium-economy, business, or first"
                )
            trip["cabin"] = cabin_map[cabin_value]
        elif option == "--flex":
            trip["flexible_dates"] = _yes_no(value, "--flex")
            if not trip["flexible_dates"]:
                trip["flexible_days"] = 0
        elif option == "--flex-days":
            try:
                flex_days = int(value)
            except ValueError as exc:
                raise ValueError("--flex-days must be a number from 1 to 7") from exc
            if not 1 <= flex_days <= 7:
                raise ValueError("--flex-days must be a number from 1 to 7")
            trip["flexible_dates"] = True
            trip["flexible_days"] = flex_days
        elif option == "--nearby":
            if value.lower() == "auto":
                trip["nearby_airports"] = False
                trip["auto_nearby"] = True
            else:
                trip["nearby_airports"] = _yes_no(value, "--nearby")
                trip["auto_nearby"] = False
        elif option == "--bags":
            if value.lower() == "auto":
                trip["auto_baggage"] = True
                index += 2
                continue
            try:
                bags = int(value)
            except ValueError as exc:
                raise ValueError("--bags must be 0, 1, or 2") from exc
            if bags not in {0, 1, 2}:
                raise ValueError("--bags must be 0, 1, or 2")
            trip["checked_bags"] = bags
            trip["auto_baggage"] = False
        elif option == "--carry-on":
            try:
                carry_on = int(value)
            except ValueError as exc:
                raise ValueError("--carry-on must be 0, 1, or 2") from exc
            if carry_on not in {0, 1, 2}:
                raise ValueError("--carry-on must be 0, 1, or 2")
            trip["carry_on_bags"] = carry_on
        elif option == "--prefer":
            trip["preferred_airlines"] = _airline_codes(value, "--prefer")
        elif option == "--avoid":
            trip["avoided_airlines"] = _airline_codes(value, "--avoid")
        elif option == "--budget":
            try:
                budget_value = float(value.replace("$", "").replace(",", ""))
            except ValueError as exc:
                raise ValueError("--budget must be a positive number") from exc
            if budget_value <= 0:
                raise ValueError("--budget must be a positive number")
            trip["max_budget"] = budget_value
        elif option == "--priority":
            try:
                trip["priority"] = Priority(value.lower())
            except ValueError as exc:
                raise ValueError(
                    "--priority must be balanced, cheapest, fastest, or nonstop"
                ) from exc
        elif option == "--max-layover":
            try:
                minutes = int(value.lower().replace("minutes", "").replace("min", ""))
            except ValueError as exc:
                raise ValueError("--max-layover must be 60 to 720 minutes") from exc
            if not 60 <= minutes <= 720:
                raise ValueError("--max-layover must be 60 to 720 minutes")
            trip["max_layover_minutes"] = minutes
        elif option == "--min-layover":
            minutes = int(value)
            if not 30 <= minutes <= 180:
                raise ValueError("--min-layover must be 30 to 180 minutes")
            trip["min_layover_minutes"] = minutes
        elif option == "--time":
            try:
                trip["departure_window"] = DepartureWindow(value.lower())
            except ValueError as exc:
                raise ValueError("--time must be any, morning, afternoon, or evening") from exc
        elif option == "--red-eye":
            normalized = value.lower()
            if normalized not in {"avoid", "allow"}:
                raise ValueError("--red-eye must be avoid or allow")
            trip["avoid_red_eye"] = normalized == "avoid"
        elif option == "--max-stops":
            if value.lower() in {"any", "none"}:
                trip["max_stops"] = None
            else:
                stops = int(value)
                if stops not in {0, 1, 2}:
                    raise ValueError("--max-stops must be 0, 1, 2, or any")
                trip["max_stops"] = stops
        elif option == "--max-duration":
            if value.lower() in {"any", "none"}:
                trip["max_total_duration_minutes"] = None
            else:
                hours = int(value.lower().replace("h", ""))
                if not 4 <= hours <= 72:
                    raise ValueError("--max-duration must be 4h to 72h or any")
                trip["max_total_duration_minutes"] = hours * 60
        elif option == "--currency":
            currency = value.upper()
            if currency not in {"USD", "CAD", "EUR", "GBP", "INR"}:
                raise ValueError("--currency must be USD, CAD, EUR, GBP, or INR")
            trip["currency"] = currency
        index += 2
    return trip


def _profile_option_present(args: list[str], option: str) -> bool:
    return any(item.lower() == option for item in args[3:])


async def _apply_saved_profile(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int | None,
    trip: dict,
    args: list[str],
) -> None:
    store: WatchStore | None = context.application.bot_data.get("watch_store")
    if not store or user_id is None:
        return
    try:
        profile = await store.get_profile(user_id)
    except Exception:
        logger.exception("Could not load saved profile; using command defaults")
        return
    if not _profile_option_present(args, "--prefer"):
        trip["preferred_airlines"] = set(profile.preferred_airlines)
    if not _profile_option_present(args, "--avoid"):
        trip["avoided_airlines"] = set(profile.avoided_airlines)
    if not _profile_option_present(args, "--budget"):
        trip["max_budget"] = profile.max_budget
    if not _profile_option_present(args, "--max-layover"):
        trip["max_layover_minutes"] = profile.max_layover_minutes
    mappings = {
        "--adults": ("adults", profile.adults),
        "--cabin": ("cabin", profile.cabin),
        "--bags": ("checked_bags", profile.checked_bags),
        "--carry-on": ("carry_on_bags", profile.carry_on_bags),
        "--currency": ("currency", profile.currency),
        "--time": ("departure_window", profile.departure_window),
        "--red-eye": ("avoid_red_eye", profile.avoid_red_eye),
        "--max-stops": ("max_stops", profile.max_stops),
        "--min-layover": ("min_layover_minutes", profile.min_layover_minutes),
        "--max-duration": ("max_total_duration_minutes", profile.max_total_duration_minutes),
    }
    for option, (key, value) in mappings.items():
        if not _profile_option_present(args, option):
            trip[key] = value


async def flight_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        args = command_arguments(update.message.text, context.args)
        trip = parse_flight_command(args)
        if not _profile_option_present(args, "--currency"):
            trip["currency"] = context.application.bot_data["settings"].default_currency
        await _apply_saved_profile(
            context,
            update.effective_user.id if update.effective_user else None,
            trip,
            args,
        )
    except ValueError as exc:
        await update.message.reply_text(
            f"Invalid flight command: {exc}\n\n"
            "Example:\n"
            "/flight JFK LAX 2026-09-15\n\n"
            "This defaults to a 7-night round trip, 4 adults, economy, flexible "
            "dates, domestic-only nearby airports, 2 checked bags, and 1 carry-on."
        )
        return ConversationHandler.END
    context.user_data["trip"] = trip
    return await show_confirmation(update, context)


def parse_quick_request(text: str) -> list[str]:
    """Parse a deliberately small, transparent natural-language grammar."""
    pattern = re.compile(
        r"^\s*(?P<origin>.+?)\s+to\s+(?P<destination>.+?)\s+"
        r"(?:on\s+)?(?P<date>\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
        r"(?:\s+for\s+(?P<days>\d+)\s+(?:days?|nights?))?"
        r"(?:\s+(?P<oneway>one[- ]way))?\s*$",
        re.I,
    )
    match = pattern.match(text)
    if not match:
        raise ValueError(
            "use: /quick New York to Paris on October 10, 2026 for 8 days"
        )
    raw_date = match.group("date")
    parsed: date | None = None
    for date_format in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
        try:
            parsed = datetime.strptime(raw_date, date_format).date()
            break
        except ValueError:
            continue
    if parsed is None or parsed < date.today():
        raise ValueError("the travel date must be today or later")
    args = [match.group("origin"), match.group("destination"), parsed.isoformat()]
    if match.group("oneway"):
        args.extend(["--trip", "one-way"])
    elif match.group("days"):
        args.extend(["--nights", match.group("days")])
    return args


async def quick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.partition(" ")[2]
    try:
        args = parse_quick_request(raw)
        trip = parse_flight_command(args)
        trip["currency"] = context.application.bot_data["settings"].default_currency
        await _apply_saved_profile(
            context,
            update.effective_user.id if update.effective_user else None,
            trip,
            args,
        )
    except ValueError as exc:
        await update.message.reply_text(f"I couldn't parse that trip: {exc}")
        return ConversationHandler.END
    context.user_data["trip"] = trip
    return await show_confirmation(update, context)


async def origin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    pending = context.user_data.pop("pending_origin_airports", None)
    if pending:
        if text.startswith("Use city: "):
            text = pending["query"]
        else:
            code = text.split(" — ", 1)[0].strip().upper()
            if code not in pending["codes"]:
                context.user_data["pending_origin_airports"] = pending
                await update.message.reply_text("Choose an airport button or Use city.")
                return ORIGIN
            text = code
    else:
        suggestions = local_airport_suggestions(text)
        if len(suggestions) > 1:
            choices = [f"{code} — {label.split('] ', 1)[-1][:32]}" for code, label, _ in suggestions]
            context.user_data["pending_origin_airports"] = {
                "query": text,
                "codes": {code for code, _, _ in suggestions},
            }
            await update.message.reply_text(
                "I found several local airport choices. Pick one for precision, "
                "or keep the city so RouteStack can choose at search time. "
                "This local check used no RouteStack search token.",
                reply_markup=_keyboard(
                    *((choice,) for choice in choices),
                    (f"Use city: {text}",),
                ),
            )
            return ORIGIN
    context.user_data["trip"]["origin"] = text
    await update.message.reply_text("Where are you flying to?")
    return DESTINATION


async def destination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    pending = context.user_data.pop("pending_destination_airports", None)
    if pending:
        if text.startswith("Use city: "):
            text = pending["query"]
        else:
            code = text.split(" — ", 1)[0].strip().upper()
            if code not in pending["codes"]:
                context.user_data["pending_destination_airports"] = pending
                await update.message.reply_text("Choose an airport button or Use city.")
                return DESTINATION
            text = code
    else:
        suggestions = local_airport_suggestions(text)
        if len(suggestions) > 1:
            choices = [f"{code} — {label.split('] ', 1)[-1][:32]}" for code, label, _ in suggestions]
            context.user_data["pending_destination_airports"] = {
                "query": text,
                "codes": {code for code, _, _ in suggestions},
            }
            await update.message.reply_text(
                "I found several destination airports. Pick one for precision, "
                "or keep the city. No RouteStack search token was used.",
                reply_markup=_keyboard(
                    *((choice,) for choice in choices),
                    (f"Use city: {text}",),
                ),
            )
            return DESTINATION
    context.user_data["trip"]["destination"] = text
    today = date.today()
    await update.message.reply_text(
        "Choose your trip start date from the calendar. You can still type "
        "YYYY-MM-DD if preferred.",
        reply_markup=_calendar_keyboard(today.year, today.month),
    )
    return DEPARTURE


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    value = year * 12 + month - 1 + offset
    return divmod(value, 12)[0], divmod(value, 12)[1] + 1


def _calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    today = date.today()
    previous_year, previous_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)
    current_month = (today.year, today.month)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "‹",
                callback_data=(
                    f"cal:nav:{previous_year:04d}-{previous_month:02d}"
                    if (year, month) > current_month
                    else "cal:noop"
                ),
            ),
            InlineKeyboardButton(
                f"{calendar.month_name[month]} {year}",
                callback_data="cal:noop",
            ),
            InlineKeyboardButton(
                "›",
                callback_data=f"cal:nav:{next_year:04d}-{next_month:02d}",
            ),
        ],
        [
            InlineKeyboardButton(day, callback_data="cal:noop")
            for day in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
        ],
    ]
    for week in calendar.monthcalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day_number in week:
            if not day_number:
                row.append(InlineKeyboardButton(" ", callback_data="cal:noop"))
                continue
            candidate = date(year, month, day_number)
            row.append(
                InlineKeyboardButton(
                    str(day_number) if candidate >= today else "·",
                    callback_data=(
                        f"cal:pick:{candidate.isoformat()}"
                        if candidate >= today
                        else "cal:noop"
                    ),
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton("Cancel", callback_data="cal:cancel")])
    return InlineKeyboardMarkup(rows)


async def calendar_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "cal:noop":
        return DEPARTURE
    if data == "cal:cancel":
        context.user_data.pop("trip", None)
        await query.edit_message_text("Search cancelled. No flight search was made.")
        return ConversationHandler.END
    if data.startswith("cal:nav:"):
        try:
            year, month = map(int, data.removeprefix("cal:nav:").split("-"))
        except ValueError:
            return DEPARTURE
        await query.edit_message_reply_markup(
            reply_markup=_calendar_keyboard(year, month)
        )
        return DEPARTURE
    try:
        parsed = date.fromisoformat(data.removeprefix("cal:pick:"))
    except ValueError:
        return DEPARTURE
    if parsed < date.today():
        await query.message.reply_text("Choose today or a future date.")
        return DEPARTURE
    context.user_data["trip"]["departure_date"] = parsed
    await query.edit_message_text(f"Start date selected: {parsed:%A, %B %d, %Y}")
    await query.message.reply_text(
        "Is this one-way or round trip?",
        reply_markup=_keyboard(("One-way", "Round trip (default)")),
    )
    return TRIP_TYPE


def _parse_future_date(text: str) -> date | None:
    try:
        parsed = date.fromisoformat(text.strip())
    except ValueError:
        return None
    return parsed if parsed >= date.today() else None


async def departure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parsed = _parse_future_date(update.message.text)
    if not parsed:
        await update.message.reply_text(
            "Please send a valid future date in YYYY-MM-DD format."
        )
        return DEPARTURE
    context.user_data["trip"]["departure_date"] = parsed
    await update.message.reply_text(
        "Is this one-way or round trip?",
        reply_markup=_keyboard(("One-way", "Round trip (default)")),
    )
    return TRIP_TYPE


async def _ask_passengers(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected = int(context.user_data["trip"].get("adults", 4))
    await message.reply_text(
        f"How many adult passengers? Your selected default is {selected}.",
        reply_markup=_keyboard(
            tuple(_default_choice(str(value), value == selected) for value in (1, 2, 3)),
            tuple(_default_choice(str(value), value == selected) for value in (4, 5, 6)),
            tuple(_default_choice(str(value), value == selected) for value in (7, 8, 9)),
        ),
    )
    return PASSENGERS


async def trip_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = re.sub(r"\s*\(default\)$", "", update.message.text.strip(), flags=re.I).lower()
    if answer not in {"one-way", "one way", "round trip", "round-trip"}:
        await update.message.reply_text("Choose One-way or Round trip.")
        return TRIP_TYPE
    if answer.startswith("one"):
        context.user_data["trip"]["return_date"] = None
        return await _ask_passengers(update.message, context)
    await update.message.reply_text(
        "How long is the round trip? Choose the number of days after departure "
        "to return. Default is 7 days.",
        reply_markup=_keyboard(
            ("3 days", "5 days", "7 days (default)"),
            ("10 days", "14 days", "21 days"),
            ("30 days",),
        ),
    )
    return RETURN


async def return_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    departing = context.user_data["trip"]["departure_date"]
    answer = update.message.text.strip()
    match = re.search(r"\d+", answer)
    duration = int(match.group()) if match else 0
    if not 1 <= duration <= 365:
        await update.message.reply_text("Choose a trip duration from 1 to 365 days.")
        return RETURN
    context.user_data["trip"]["return_date"] = departing + timedelta(days=duration)
    return await _ask_passengers(update.message, context)


async def passengers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    match = re.search(r"\d+", update.message.text.strip())
    count = int(match.group()) if match else 0
    if not 1 <= count <= 9:
        await update.message.reply_text("Enter a number from 1 to 9.")
        return PASSENGERS
    context.user_data["trip"]["adults"] = count
    default_cabin = context.user_data["trip"].get("cabin", Cabin.ECONOMY)
    await update.message.reply_text(
        "Cabin class?",
        reply_markup=_keyboard(
            (_default_choice("Economy", default_cabin == Cabin.ECONOMY), _default_choice("Premium economy", default_cabin == Cabin.PREMIUM_ECONOMY)),
            (_default_choice("Business", default_cabin == Cabin.BUSINESS), _default_choice("First", default_cabin == Cabin.FIRST)),
        ),
    )
    return CABIN


async def cabin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = re.sub(r"\s*\(default\)$", "", update.message.text.strip(), flags=re.I).lower().replace(" ", "_")
    mapping = {
        "economy": Cabin.ECONOMY,
        "premium_economy": Cabin.PREMIUM_ECONOMY,
        "business": Cabin.BUSINESS,
        "first": Cabin.FIRST,
    }
    if value not in mapping:
        await update.message.reply_text("Choose one of the cabin options.")
        return CABIN
    context.user_data["trip"]["cabin"] = mapping[value]
    default_currency = context.user_data["trip"].get("currency", "USD")
    await update.message.reply_text(
        "Display currency? This changes the currency requested from the provider; "
        "it does not perform a local exchange-rate estimate.",
        reply_markup=_keyboard(
            tuple(_default_choice(item, item == default_currency) for item in ("USD", "CAD", "EUR")),
            tuple(_default_choice(item, item == default_currency) for item in ("GBP", "INR")),
        ),
    )
    return CURRENCY


async def currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = re.sub(r"\s*\(default\)$", "", update.message.text.strip(), flags=re.I).upper()
    if value not in {"USD", "CAD", "EUR", "GBP", "INR"}:
        await update.message.reply_text("Choose USD, CAD, EUR, GBP, or INR.")
        return CURRENCY
    context.user_data["trip"]["currency"] = value
    default_window = context.user_data["trip"].get("departure_window", DepartureWindow.ANY)
    await update.message.reply_text(
        "Preferred outbound departure time? Any time finds the widest selection. "
        "Other choices remain preferences: mismatches stay visible with a warning.",
        reply_markup=_keyboard(
            (_default_choice("Any time", default_window == DepartureWindow.ANY),),
            tuple(_default_choice(label, default_window.value == label.lower()) for label in ("Morning", "Afternoon", "Evening")),
        ),
    )
    return TIME_PREF


async def time_preference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = re.sub(r"\s*time|\s*\(default\)", "", update.message.text.strip(), flags=re.I).lower()
    try:
        context.user_data["trip"]["departure_window"] = DepartureWindow(value)
    except ValueError:
        await update.message.reply_text("Choose Any time, Morning, Afternoon, or Evening.")
        return TIME_PREF
    default_stops = context.user_data["trip"].get("max_stops")
    await update.message.reply_text(
        "Maximum stops? Any keeps every fare. Options above your preference remain "
        "visible but are highlighted and ranked lower.",
        reply_markup=_keyboard(
            (_default_choice("Any stops", default_stops is None),),
            (_default_choice("Nonstop only", default_stops == 0), _default_choice("Maximum 1", default_stops == 1), _default_choice("Maximum 2", default_stops == 2)),
        ),
    )
    return MAX_STOPS


async def max_stops(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer.startswith("any"):
        value = None
    elif answer.startswith("nonstop"):
        value = 0
    else:
        match = re.search(r"\d+", answer)
        value = int(match.group()) if match else -1
        if value not in {1, 2}:
            await update.message.reply_text("Choose Any stops, Nonstop only, Maximum 1, or Maximum 2.")
            return MAX_STOPS
    context.user_data["trip"]["max_stops"] = value
    avoid_default = context.user_data["trip"].get("avoid_red_eye", True)
    await update.message.reply_text(
        "Red-eye preference? Avoid is the comfort-focused default. Red-eye fares "
        "still appear, but receive a clear warning and ranking penalty.",
        reply_markup=_keyboard((_default_choice("Avoid red-eyes", avoid_default), _default_choice("Allow red-eyes", not avoid_default))),
    )
    return RED_EYE


async def red_eye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if not answer.startswith(("avoid", "allow")):
        await update.message.reply_text("Choose Avoid red-eyes or Allow red-eyes.")
        return RED_EYE
    context.user_data["trip"]["avoid_red_eye"] = answer.startswith("avoid")
    connection_default = (
        context.user_data["trip"].get("min_layover_minutes", 60),
        context.user_data["trip"].get("max_layover_minutes", 300),
    )
    await update.message.reply_text(
        "Connection comfort? Standard allows 1–5 hour layovers. Short accepts "
        "45 minutes; Comfortable asks for at least 90 minutes; Wide allows up to 8 hours.",
        reply_markup=_keyboard(
            (_default_choice("Standard 1–5h", connection_default == (60, 300)),),
            (_default_choice("Short 45m–3h", connection_default == (45, 180)), _default_choice("Comfortable 90m–6h", connection_default == (90, 360))),
            (_default_choice("Wide 45m–8h", connection_default == (45, 480)),),
        ),
    )
    return CONNECTION


async def connection_preference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    presets = {"standard": (60, 300), "short": (45, 180), "comfortable": (90, 360), "wide": (45, 480)}
    selected = next((value for label, value in presets.items() if answer.startswith(label)), None)
    if not selected:
        await update.message.reply_text("Choose one of the connection presets.")
        return CONNECTION
    context.user_data["trip"]["min_layover_minutes"], context.user_data["trip"]["max_layover_minutes"] = selected
    duration_default = context.user_data["trip"].get("max_total_duration_minutes")
    await update.message.reply_text(
        "Maximum travel time per direction? No limit keeps all results. Longer "
        "options remain visible but are highlighted and ranked lower.",
        reply_markup=_keyboard(
            (_default_choice("No duration limit", duration_default is None),),
            tuple(_default_choice(f"{hours} hours", duration_default == hours * 60) for hours in (12, 18, 24)),
            (_default_choice("36 hours", duration_default == 2160),),
        ),
    )
    return DURATION_LIMIT


async def duration_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer.startswith("no"):
        value = None
    else:
        match = re.search(r"\d+", answer)
        value = int(match.group()) * 60 if match else -1
        if value not in {720, 1080, 1440, 2160}:
            await update.message.reply_text("Choose No limit, 12, 18, 24, or 36 hours.")
            return DURATION_LIMIT
    context.user_data["trip"]["max_total_duration_minutes"] = value
    await update.message.reply_text(
        "Are your travel dates flexible? Yes can reveal cheaper travel days; no "
        "keeps the exact date.",
        reply_markup=_keyboard(("Yes (default)", "No")),
    )
    return FLEXIBLE


async def flexible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower().split(" ", 1)[0]
    if answer not in {"yes", "no"}:
        await update.message.reply_text("Please choose Yes or No.")
        return FLEXIBLE
    context.user_data["trip"]["flexible_dates"] = answer == "yes"
    if answer == "yes":
        await update.message.reply_text(
            "How many days earlier or later can you travel? Default is ±3 days.",
            reply_markup=_keyboard(
                ("±1 day", "±2 days", "±3 days (default)"),
                ("±5 days", "±7 days"),
            ),
        )
        return FLEX_DAYS
    context.user_data["trip"]["flexible_days"] = 0
    return await _ask_nearby(update.message)


async def flexible_days(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    match = re.search(r"\d+", update.message.text.strip())
    days = int(match.group()) if match else 0
    if not 1 <= days <= 7:
        await update.message.reply_text("Choose a flexible range from ±1 to ±7 days.")
        return FLEX_DAYS
    context.user_data["trip"]["flexible_days"] = days
    return await _ask_nearby(update.message)


async def _ask_nearby(message) -> int:
    await message.reply_text(
        "Include nearby airports? Auto is recommended: yes for domestic trips "
        "and no for international trips.",
        reply_markup=_keyboard(("Auto (recommended)",), ("Yes", "No")),
    )
    return NEARBY


async def nearby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer.startswith("auto"):
        context.user_data["trip"]["nearby_airports"] = False
        context.user_data["trip"]["auto_nearby"] = True
    elif answer in {"yes", "no"}:
        context.user_data["trip"]["nearby_airports"] = answer == "yes"
        context.user_data["trip"]["auto_nearby"] = False
    else:
        await update.message.reply_text("Choose Auto, Yes, or No.")
        return NEARBY
    default_bags = context.user_data["trip"].get("checked_bags", 2)
    await update.message.reply_text(
        f"How many checked/check-in bags per traveler? Your selected default is {default_bags}. Smart uses "
        "0 domestically or 2 internationally.",
        reply_markup=_keyboard(
            tuple(_default_choice(f"{value} checked", value == default_bags) for value in (0, 1, 2)),
            ("Smart by route",),
        ),
    )
    return BAGS


async def bags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip().lower().startswith("smart"):
        context.user_data["trip"]["checked_bags"] = 0
        context.user_data["trip"]["auto_baggage"] = True
    else:
        match = re.search(r"\d+", update.message.text.strip())
        count = int(match.group()) if match else -1
        if count not in {0, 1, 2}:
            await update.message.reply_text("Choose 0, 1, 2, or Smart by route.")
            return BAGS
        context.user_data["trip"]["checked_bags"] = count
        context.user_data["trip"]["auto_baggage"] = False
    default_carry = context.user_data["trip"].get("carry_on_bags", 1)
    await update.message.reply_text(
        f"How many carry-on bags per traveler? Your selected default is {default_carry}.",
        reply_markup=_keyboard(tuple(
            _default_choice(f"{value} carry-on{'s' if value != 1 else ''}", value == default_carry)
            for value in (0, 1, 2)
        )),
    )
    return CARRY_ON


async def carry_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    match = re.search(r"\d+", update.message.text.strip())
    count = int(match.group()) if match else -1
    if count not in {0, 1, 2}:
        await update.message.reply_text("Choose 0, 1, or 2 carry-on bags.")
        return CARRY_ON
    context.user_data["trip"]["carry_on_bags"] = count
    trip = context.user_data["trip"]
    has_saved = bool(trip.get("preferred_airlines") or trip.get("avoided_airlines"))
    await update.message.reply_text(
        "Airline preferences? Use IATA codes like:\n"
        "prefer: DL,UA; avoid: F9,NK\n\n"
        "The default keeps your saved profile, or no restrictions if none are saved.",
        reply_markup=_keyboard((("Use saved (default)" if has_saved else "None (default)"),)),
    )
    return AIRLINES


def _parse_airlines(text: str) -> tuple[set[str], set[str]] | None:
    if text.strip().lower() in {"none", "no", "n/a"}:
        return set(), set()
    preferred: set[str] = set()
    avoided: set[str] = set()
    for part in text.upper().split(";"):
        if ":" not in part:
            return None
        label, values = part.split(":", 1)
        codes = {code.strip() for code in values.split(",") if code.strip()}
        if any(not re.fullmatch(r"[A-Z0-9]{2}", code) for code in codes):
            return None
        if label.strip() in {"PREFER", "PREFERRED"}:
            preferred |= codes
        elif label.strip() in {"AVOID", "AVOIDED"}:
            avoided |= codes
        else:
            return None
    return preferred, avoided


async def airlines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip()
    if answer.lower().startswith("use saved"):
        parsed = (
            set(context.user_data["trip"].get("preferred_airlines", set())),
            set(context.user_data["trip"].get("avoided_airlines", set())),
        )
    else:
        parsed = _parse_airlines(re.sub(r"\s*\(default\)$", "", answer, flags=re.I))
    if parsed is None:
        await update.message.reply_text(
            "Use “none” or this format: prefer: DL,UA; avoid: F9,NK"
        )
        return AIRLINES
    preferred, avoided = parsed
    context.user_data["trip"]["preferred_airlines"] = preferred
    context.user_data["trip"]["avoided_airlines"] = avoided
    await update.message.reply_text(
        f"Maximum airfare budget in {context.user_data['trip'].get('currency', 'USD')} for everyone? These planning limits "
        "adjust for your route type, cabin, trip type, and passenger count. "
        "Optional baggage/seat fees may be extra.",
        reply_markup=_budget_keyboard(context.user_data["trip"]),
    )
    return BUDGET


def _round_budget(value: float) -> int:
    if value < 5_000:
        step = 250
    elif value < 15_000:
        step = 500
    else:
        step = 1_000
    return max(step, int(round(value / step) * step))


def common_budget_values(trip: dict) -> tuple[int, ...]:
    """Return researched planning bands, not live fare predictions.

    Domestic anchors reflect 2026 BTS average-itinerary data and late-2025 ARC
    economy/premium ticket reporting. International bands are intentionally wider
    because distance and market variation dominate a single global average.
    """
    def country_hint(query: str) -> str:
        exact = local_airport(query)
        if exact:
            return exact[2]
        suggestions = local_airport_suggestions(query)
        countries = {item[2] for item in suggestions if item[2]}
        return next(iter(countries)) if len(countries) == 1 else ""

    origin_country = country_hint(str(trip.get("origin", "")))
    destination_country = country_hint(str(trip.get("destination", "")))
    domestic = is_domestic(origin_country, destination_country)
    cabin = trip.get("cabin", Cabin.ECONOMY)
    if domestic:
        per_person = {
            Cabin.ECONOMY: 500,
            Cabin.PREMIUM_ECONOMY: 750,
            Cabin.BUSINESS: 1_400,
            Cabin.FIRST: 1_800,
        }[cabin]
    else:
        per_person = {
            Cabin.ECONOMY: 1_000,
            Cabin.PREMIUM_ECONOMY: 1_600,
            Cabin.BUSINESS: 3_500,
            Cabin.FIRST: 6_000,
        }[cabin]
    if not trip.get("return_date"):
        per_person *= 0.6
    center = per_person * int(trip.get("adults", 4))
    values = {
        _round_budget(center * multiplier)
        for multiplier in (0.75, 1.0, 1.25, 1.75)
    }
    while len(values) < 4:
        highest = max(values)
        increment = 250 if highest < 5_000 else 500 if highest < 15_000 else 1_000
        values.add(highest + increment)
    return tuple(sorted(values))


def _budget_keyboard(trip: dict) -> ReplyKeyboardMarkup:
    currency_code = trip.get("currency", "USD")
    values = [f"{currency_code} {value:,}" for value in common_budget_values(trip)]
    default_budget = trip.get("max_budget")
    default_button = (
        f"{currency_code} {default_budget:,.0f} (saved default)"
        if default_budget is not None
        else "No maximum (default)"
    )
    return _keyboard(
        tuple(values[:2]),
        tuple(values[2:]),
        ("Custom amount", default_button),
    )


async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_answer = update.message.text.strip()
    if raw_answer.lower().endswith("(saved default)"):
        value = context.user_data["trip"].get("max_budget")
        context.user_data["trip"]["max_budget"] = value
        return await _ask_priority(update.message)
    answer = re.sub(r"\s*\(default\)$", "", raw_answer, flags=re.I).lower()
    answer = re.sub(r"^(usd|cad|eur|gbp|inr)\s+", "", answer).replace("$", "").replace(",", "")
    if answer == "custom amount":
        await update.message.reply_text(
            "Enter your custom maximum airfare budget in USD for all travelers, "
            "for example 2750.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return BUDGET
    if answer in {"none", "no", "n/a", "no maximum"}:
        value = None
    else:
        try:
            value = float(answer)
        except ValueError:
            value = -1
        if value <= 0:
            await update.message.reply_text("Send a positive number or “none”.")
            return BUDGET
    context.user_data["trip"]["max_budget"] = value
    return await _ask_priority(update.message)


async def _ask_priority(message) -> int:
    await message.reply_text(
        "How should I sort the results?\n"
        "• Cheapest: puts price first\n"
        "• Balanced: best mix of price, duration, and stops\n"
        "• Fastest: puts total travel time first\n"
        "• Nonstop: strongly favors zero stops",
        reply_markup=_keyboard(
            ("Cheapest", "Balanced (default)"), ("Fastest", "Nonstop")
        ),
    )
    return PRIORITY


async def priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = re.sub(r"\s*\(default\)$", "", update.message.text.strip(), flags=re.I).lower()
    try:
        selected = Priority(answer)
    except ValueError:
        await update.message.reply_text("Choose one of the four options.")
        return PRIORITY
    context.user_data["trip"]["priority"] = selected
    return await show_confirmation(update, context)


async def show_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    trip = context.user_data["trip"]
    return_text = (
        trip["return_date"].isoformat() if trip["return_date"] else "one-way"
    )
    budget_text = (
        f"{trip.get('currency', 'USD')} {trip['max_budget']:,.2f}" if trip["max_budget"] else "no maximum"
    )
    nearby_search_allowance = _nearby_search_allowance(trip)
    flexible_days_value = int(trip.get("flexible_days", 3))
    maximum_provider_calls = (
        2 * flexible_days_value + 1 if trip["flexible_dates"] else 1
    ) + nearby_search_allowance
    nearby_text = (
        "smart: yes domestic; no international"
        if trip.get("auto_nearby")
        else ("yes" if trip["nearby_airports"] else "no")
    )
    baggage_text = (
        "smart checked: 0 domestic or 2 international; "
        f"{trip.get('carry_on_bags', 1)} carry-on"
        if trip.get("auto_baggage")
        else (
            f"{trip['checked_bags']} checked + "
            f"{trip.get('carry_on_bags', 1)} carry-on each"
        )
    )
    date_advice = ""
    confirmation_buttons: tuple[str, ...]
    if trip["flexible_dates"]:
        suggested = suggested_departure_date(
            trip["departure_date"], flexible_days_value
        )
        trip["suggested_departure_date"] = suggested
        shift = (suggested - trip["departure_date"]).days
        shift_text = (
            "the requested date"
            if shift == 0
            else f"{abs(shift)} day(s) {'later' if shift > 0 else 'earlier'}"
        )
        date_advice = (
            "\n📅 Free date estimate (no API call): "
            f"{suggested:%A, %Y-%m-%d} ({shift_text}).\n"
            "This uses a broad U.S. historical Monday–Wednesday travel trend, "
            "not live route prices. It may not apply to every market. Choose the "
            "full comparison to know the cheapest live date.\n"
            f"Suggested-date search: up to {1 + nearby_search_allowance} "
            "RouteStack search token(s).\n"
        )
        confirmation_buttons = (
            "Smart progressive search",
            "Search suggested date",
            f"Compare all ±{flexible_days_value} days",
            "Cancel",
        )
    else:
        confirmation_buttons = ("Search now", "Cancel")
    usage_label = (
        "Full flexible comparison"
        if trip["flexible_dates"]
        else "Planned search"
    )

    airport_hint_lines: list[str] = []
    for label, value in (
        ("Origin", trip["origin"]),
        ("Destination", trip["destination"]),
    ):
        suggestions = local_airport_suggestions(str(value))
        if len(suggestions) > 1:
            codes = ", ".join(code for code, _, _ in suggestions)
            airport_hint_lines.append(
                f"{label} local airport choices: {codes}. Use a code for precision; "
                "keeping the city lets RouteStack choose."
            )
    airport_hint = (
        "\n🛫 Local airport check (no API token):\n"
        + "\n".join(airport_hint_lines)
        + "\n"
        if airport_hint_lines
        else ""
    )

    await update.message.reply_text(
        "Please confirm:\n"
        f"{trip['origin']} → {trip['destination']}\n"
        f"Depart: {trip['departure_date']} | Return: {return_text}\n"
        f"{trip['adults']} adult(s) | {trip['cabin'].value.replace('_', ' ').title()}\n"
        f"Trip duration: "
        f"{(trip['return_date'] - trip['departure_date']).days if trip['return_date'] else 'one-way'}"
        f"{' days' if trip['return_date'] else ''}\n"
        f"Flexible: "
        f"{'yes, ±' + str(flexible_days_value) + ' days' if trip['flexible_dates'] else 'no'} | "
        f"Nearby airports: {nearby_text} | "
        f"Baggage: {baggage_text}\n"
        f"Budget: {budget_text} | Ranking: {trip['priority'].value}\n\n"
        f"Currency: {trip.get('currency', 'USD')} | Departure: "
        f"{trip.get('departure_window', DepartureWindow.ANY).value} | "
        f"Red-eyes: {'avoid' if trip.get('avoid_red_eye', True) else 'allow'} | "
        f"Max stops: {trip.get('max_stops') if trip.get('max_stops') is not None else 'any'}\n"
        f"Connections: {trip.get('min_layover_minutes', 60)}–"
        f"{trip.get('max_layover_minutes', 300)} min | Max time/direction: "
        f"{str(trip.get('max_total_duration_minutes') // 60) + 'h' if trip.get('max_total_duration_minutes') else 'none'}\n\n"
        f"{usage_label}: up to {maximum_provider_calls} "
        f"RouteStack search token(s).\n"
        f"{date_advice}\n"
        f"{airport_hint}"
        "Search live fares now?",
        reply_markup=_keyboard(*((button,) for button in confirmation_buttons)),
    )
    return CONFIRM


def _nearby_search_allowance(trip: dict) -> int:
    if not trip.get("auto_nearby"):
        return 4 if trip.get("nearby_airports") else 0
    origin = local_airport(str(trip.get("origin", "")))
    destination = local_airport(str(trip.get("destination", "")))
    if origin and destination:
        return 4 if is_domestic(origin[2], destination[2]) else 0
    # Free-text cities need provider resolution, so disclose the safe maximum.
    return 4


def suggested_departure_date(departure: date, flexible_days: int = 3) -> date:
    """Choose a no-call weekday candidate within the allowed flexible range.

    This is deliberately a broad calendar heuristic, not a fare prediction.
    Monday through Wednesday are preferred, followed by Thursday, Saturday,
    Friday, and Sunday. The closest date wins within the same tier.
    """
    weekday_tier = {
        0: 0,  # Monday
        1: 0,  # Tuesday
        2: 0,  # Wednesday
        3: 1,  # Thursday
        5: 2,  # Saturday
        4: 3,  # Friday
        6: 3,  # Sunday
    }
    candidates = [
        departure + timedelta(days=shift)
        for shift in range(-flexible_days, flexible_days + 1)
        if departure + timedelta(days=shift) >= date.today()
    ]
    return min(
        candidates,
        key=lambda candidate: (
            weekday_tier[candidate.weekday()],
            abs((candidate - departure).days),
            candidate,
        ),
    )


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer == "cancel":
        return await cancel(update, context)
    trip = context.user_data["trip"]
    progressive = answer == "smart progressive search" and trip["flexible_dates"]
    if progressive:
        trip.pop("suggested_departure_date", None)
    elif answer == "search suggested date" and trip["flexible_dates"]:
        suggested = trip.pop("suggested_departure_date")
        shift = suggested - trip["departure_date"]
        trip["departure_date"] = suggested
        if trip["return_date"]:
            trip["return_date"] += shift
        trip["flexible_dates"] = False
    elif answer.startswith("compare all ±") and trip["flexible_dates"]:
        trip.pop("suggested_departure_date", None)
    elif answer == "search now":
        trip.pop("suggested_departure_date", None)
    else:
        await update.message.reply_text(
            "Choose Smart progressive search, Search suggested date, "
            f"Compare all ±{trip.get('flexible_days', 3)} days, or Cancel."
            if trip["flexible_dates"]
            else "Choose Search now or Cancel."
        )
        return CONFIRM

    await update.message.reply_text(
        "Searching live fares and comparing the best options…",
        reply_markup=ReplyKeyboardRemove(),
    )
    request = SearchRequest(**trip)
    client: RouteStackClient = context.application.bot_data["routestack"]
    try:
        if progressive:
            (
                offers,
                origin_label,
                destination_label,
                request,
                search_note,
            ) = await _progressive_search(client, request)
        else:
            offers, origin_label, destination_label = await client.search(request)
            search_note = (
                f"full ±{request.flexible_days}-day and eligible nearby-airport comparison"
                if request.flexible_dates
                else "single-date search"
            )
        results = rank_flights(offers, request)
        if not results:
            await update.message.reply_text(
                "No matching live offers were returned. Try nearby dates, a higher "
                "budget, fewer baggage restrictions, or nearby airports."
            )
        else:
            observed_prices: list[float] | None = None
            store: WatchStore | None = context.application.bot_data.get("watch_store")
            user_id = update.effective_user.id if update.effective_user else None
            best = results.cheapest
            if store and user_id is not None:
                try:
                    route_origin = best.legs[0].origin
                    route_destination = best.legs[0].destination
                    observed_prices = await store.route_prices(
                        user_id,
                        route_origin,
                        route_destination,
                        best.currency,
                    )
                    await store.record_search(
                        user_id,
                        request,
                        route_origin,
                        route_destination,
                        best.total_price,
                        best.currency,
                    )
                except Exception:
                    logger.exception("Could not update saved search history")
            message = format_results(
                results,
                request,
                origin_label,
                destination_label,
                observed_prices=observed_prices,
                search_note=search_note,
            )
            await update.message.reply_text(
                message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=_booking_keyboard(
                    _store_booking_options(context, results, request)
                ),
            )
    except FlightSearchError as exc:
        logger.warning("Flight search failed: %s", exc)
        await update.message.reply_text(
            f"I couldn't complete the live search: {exc}\n"
            "No price estimate was substituted. Please try again."
        )
    except Exception:
        logger.exception("Unexpected search error")
        await update.message.reply_text(
            "The live search failed unexpectedly. No price estimate was substituted. "
            "Please try again shortly."
        )
    finally:
        context.user_data.pop("trip", None)
    return ConversationHandler.END


def _deduplicate_offers(offers: list[FlightOption]) -> list[FlightOption]:
    unique: dict[tuple, FlightOption] = {}
    for offer in offers:
        key = (
            offer.airline_codes,
            tuple((leg.origin, leg.destination, leg.departure, leg.arrival) for leg in offer.legs),
            offer.total_price,
        )
        unique.setdefault(key, offer)
    return list(unique.values())


def _has_satisfactory_offer(
    offers: list[FlightOption], request: SearchRequest
) -> bool:
    results = rank_flights(offers, request)
    return bool(
        results
        and any(
            not itinerary_risks(option)
            for option in results.ordered[:5]
        )
    )


async def _progressive_search(
    client: RouteStackClient, request: SearchRequest
) -> tuple[list[FlightOption], str, str, SearchRequest, str]:
    """Spend search calls in stages and stop once a usable itinerary appears."""
    suggested = suggested_departure_date(
        request.departure_date, request.flexible_days
    )
    shift = suggested - request.departure_date
    first_request = replace(
        request,
        departure_date=suggested,
        return_date=(request.return_date + shift if request.return_date else None),
        flexible_dates=False,
        nearby_airports=False,
        auto_nearby=False,
    )
    offers, origin_label, destination_label = await client.search(first_request)
    if _has_satisfactory_offer(offers, first_request):
        return (
            offers,
            origin_label,
            destination_label,
            first_request,
            "stopped after 1 suggested-date search because usable results were found",
        )

    date_request = replace(
        request,
        flexible_dates=True,
        nearby_airports=False,
        auto_nearby=False,
    )
    date_offers, origin_label, destination_label = await client.search(date_request)
    combined = _deduplicate_offers([*offers, *date_offers])
    if _has_satisfactory_offer(combined, date_request):
        return (
            combined,
            origin_label,
            destination_label,
            date_request,
            f"expanded to ±{request.flexible_days} days because the first stage "
            "had no usable low-risk result",
        )

    if not request.auto_nearby and not request.nearby_airports:
        return (
            combined,
            origin_label,
            destination_label,
            date_request,
            f"expanded to ±{request.flexible_days} days; nearby airports were "
            "disabled by the request",
        )
    airport_request = replace(request, flexible_dates=True)
    airport_offers, origin_label, destination_label = await client.search(
        airport_request
    )
    combined = _deduplicate_offers([*combined, *airport_offers])
    airport_note = (
        "expanded to eligible domestic nearby airports after date results "
        "remained limited or risky"
        if airport_request.nearby_airports
        else f"expanded to ±{request.flexible_days} days; nearby airports stayed "
        "off for this route"
    )
    return (
        combined,
        origin_label,
        destination_label,
        airport_request,
        airport_note,
    )


def _store_booking_options(
    context: ContextTypes.DEFAULT_TYPE,
    results,
    request: SearchRequest,
) -> tuple[str, list[FlightOption], SearchRequest]:
    options = [
        option
        for option in selected_results(results, limit=3)
        if option.booking_payload
    ]
    token = secrets.token_urlsafe(6)
    handoffs = context.user_data.setdefault("booking_handoffs", {})
    handoffs[token] = {
        "request": request,
        "options": options,
    }
    while len(handoffs) > 3:
        handoffs.pop(next(iter(handoffs)))
    return token, options, request


def _booking_keyboard(
    handoff: tuple[str, list[FlightOption], SearchRequest]
) -> InlineKeyboardMarkup | None:
    token, options, request = handoff
    if not options:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for rank, option in enumerate(options, 1):
        rows.extend(
            [
            [
                InlineKeyboardButton(
                    f"Exact option #{rank}",
                    callback_data=f"checkout:{token}:{rank - 1}",
                ),
                InlineKeyboardButton(
                    f"Expedia #{rank}",
                    url=expedia_search_url(option, request),
                ),
            ]
            ,
            [
                InlineKeyboardButton(
                    f"Google Flights #{rank}",
                    url=google_flights_url(option, request),
                ),
                InlineKeyboardButton(
                    f"Kayak #{rank}",
                    url=kayak_search_url(option, request),
                ),
            ],
            ]
        )
    return InlineKeyboardMarkup(rows)


async def checkout_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    try:
        _, token, raw_index = query.data.split(":", 2)
        index = int(raw_index)
    except (AttributeError, ValueError, IndexError):
        await query.message.reply_text("That booking selection is invalid.")
        return

    handoff = (
        context.user_data.get("booking_handoffs", {}).get(token) or {}
    )
    options: list[FlightOption] = handoff.get("options") or []
    request: SearchRequest | None = handoff.get("request")
    if request is None or not 0 <= index < len(options):
        await query.message.reply_text(
            "These results are no longer available. Run a new /search so the "
            "price can be checked again."
        )
        return

    option = options[index]
    logger.info(
        "booking_handoff_clicked route=%s-%s rank=%d source=%s",
        option.legs[0].origin,
        option.legs[0].destination,
        index + 1,
        option.source,
    )
    await query.message.reply_text(
        f"Rechecking option #{index + 1}'s live price and availability…"
    )
    client: RouteStackClient = context.application.bot_data["routestack"]
    try:
        url = await client.create_checkout_url(option, request)
    except FlightSearchError as exc:
        logger.warning("Checkout handoff failed: %s", exc)
        await query.message.reply_text(
            f"I couldn't create a current checkout link: {exc}\n"
            "No booking or charge was made. You can compare the same route, "
            "dates, cabin, and airline on Expedia, but its fare may differ.",
            reply_markup=InlineKeyboardMarkup(
                [
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
            ),
        )
        return
    await query.message.reply_text(
        "The fare was rechecked. Continue on RouteStack's secure hosted checkout "
        "to verify the final price, baggage and fare rules.\n\n"
        "Expedia opens a separate search for the same trip and airline; it may "
        "show a different itinerary or price.\n\n"
        "The Telegram bot does not collect payment or issue the ticket.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Open exact RouteStack offer", url=url)],
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
        ),
    )


async def airports_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(
            "Use /airports followed by a city and optional state, for example:\n"
            "/airports New York, NY\n\n"
            "This helper uses the bot's local airport database and no RouteStack "
            "search token."
        )
        return
    suggestions = local_airport_suggestions(query, limit=8)
    if not suggestions:
        await update.message.reply_text(
            f"No local airport match was found for “{query}”. Try the guided "
            "/search flow; provider location resolution occurs only when you "
            "confirm a live search."
        )
        return
    lines = [
        f"🛫 Local airport matches for {query}",
        "No RouteStack search token used.",
        "",
    ]
    lines.extend(f"• {code} — {label}" for code, label, _ in suggestions)
    lines.append("\nUse the three-letter code in /flight for the most precise result.")
    await update.message.reply_text("\n".join(lines))


async def recent_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    store: WatchStore | None = context.application.bot_data.get("watch_store")
    user_id = update.effective_user.id if update.effective_user else None
    if not store or user_id is None:
        await update.message.reply_text(
            "Recent searches require the configured Railway Postgres database."
        )
        return
    recent = await store.list_recent(user_id, limit=5)
    if not recent:
        await update.message.reply_text(
            "No successful searches are saved yet. Run /flight or /search first."
        )
        return
    lines = ["🕘 Recent successful searches"]
    for position, item in enumerate(recent, 1):
        lines.append(
            f"{position}. {item.request.origin} → {item.request.destination} | "
            f"{item.request.departure_date} | {item.currency} "
            f"{item.best_price:,.2f}"
        )
    lines.append(
        "\nUse /repeat NUMBER to review and confirm one. Listing and repeating "
        "use no search token until you approve the live search."
    )
    await update.message.reply_text("\n".join(lines))


async def repeat_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    store: WatchStore | None = context.application.bot_data.get("watch_store")
    user_id = update.effective_user.id if update.effective_user else None
    if not store or user_id is None:
        await update.message.reply_text(
            "Repeat search requires the configured Railway Postgres database."
        )
        return ConversationHandler.END
    try:
        position = int(context.args[0]) if context.args else 1
    except ValueError:
        await update.message.reply_text("Use /repeat NUMBER, for example /repeat 1.")
        return ConversationHandler.END
    recent = await store.get_recent(user_id, position)
    if not recent:
        await update.message.reply_text(
            "That recent-search number was not found. Use /recent to list them."
        )
        return ConversationHandler.END
    context.user_data["trip"] = asdict(recent.request)
    return await show_confirmation(update, context)


def _profile_text(profile: UserProfile) -> str:
    preferred = ",".join(sorted(profile.preferred_airlines)) or "none"
    avoided = ",".join(sorted(profile.avoided_airlines)) or "none"
    budget = (
        f"${profile.max_budget:,.2f}" if profile.max_budget is not None else "none"
    )
    return (
        "👤 Saved one-line search profile\n"
        f"Preferred airlines: {preferred}\n"
        f"Avoided airlines: {avoided}\n"
        f"Default budget: {budget}\n"
        f"Travelers/cabin: {profile.adults} adult(s), {profile.cabin.value.replace('_', ' ').title()}\n"
        f"Baggage: {profile.checked_bags} checked + {profile.carry_on_bags} carry-on\n"
        f"Currency/time: {profile.currency}, {profile.departure_window.value}\n"
        f"Red-eyes: {'avoid' if profile.avoid_red_eye else 'allow'} | "
        f"Max stops: {profile.max_stops if profile.max_stops is not None else 'any'}\n"
        f"Layover preference: {profile.min_layover_minutes}–{profile.max_layover_minutes} minutes\n"
        f"Maximum duration: {profile.max_total_duration_minutes // 60 if profile.max_total_duration_minutes else 'none'}"
        f"{' hours' if profile.max_total_duration_minutes else ''}\n"
        f"Timezone/quiet hours: {profile.timezone}, "
        f"{profile.quiet_start_hour:02d}:00–{profile.quiet_end_hour:02d}:00"
    )


async def profile_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    store: WatchStore | None = context.application.bot_data.get("watch_store")
    user_id = update.effective_user.id if update.effective_user else None
    if not store or user_id is None:
        await update.message.reply_text(
            "Saved profiles require the configured Railway Postgres database."
        )
        return
    current = await store.get_profile(user_id)
    args = context.args
    if not args:
        await update.message.reply_text(
            _profile_text(current)
            + "\n\nUpdate example:\n"
            "/profile --prefer DL,UA --avoid NK,F9 --budget 900 "
            "--adults 4 --cabin economy --bags 2 --carry-on 1 --currency USD "
            "--time any --red-eye avoid --max-stops any --min-layover 60 "
            "--max-layover 300 --max-duration none "
            "--timezone America/New_York --quiet 22-7\n"
            "Use /profile --clear to restore defaults. This command uses no "
            "RouteStack search token."
        )
        return
    if len(args) == 1 and args[0].lower() == "--clear":
        saved = await store.save_profile(
            user_id, UserProfile(set(), set(), None, 300)
        )
        await update.message.reply_text(_profile_text(saved) + "\nProfile reset.")
        return
    preferred = set(current.preferred_airlines)
    avoided = set(current.avoided_airlines)
    budget = current.max_budget
    max_layover = current.max_layover_minutes
    values = {
        "adults": current.adults, "cabin": current.cabin,
        "checked_bags": current.checked_bags, "carry_on_bags": current.carry_on_bags,
        "currency": current.currency, "departure_window": current.departure_window,
        "avoid_red_eye": current.avoid_red_eye, "max_stops": current.max_stops,
        "min_layover_minutes": current.min_layover_minutes,
        "max_total_duration_minutes": current.max_total_duration_minutes,
        "timezone": current.timezone,
        "quiet_start_hour": current.quiet_start_hour,
        "quiet_end_hour": current.quiet_end_hour,
    }
    allowed = {"--prefer", "--avoid", "--budget", "--max-layover", "--adults", "--cabin", "--bags", "--carry-on", "--currency", "--time", "--red-eye", "--max-stops", "--min-layover", "--max-duration", "--timezone", "--quiet"}
    index = 0
    try:
        while index < len(args):
            option = args[index].lower()
            if option not in allowed or index + 1 >= len(args):
                raise ValueError(
                    "use a documented /profile option with a value"
                )
            value = args[index + 1]
            if option == "--prefer":
                preferred = _airline_codes(value, option)
            elif option == "--avoid":
                avoided = _airline_codes(value, option)
            elif option == "--budget":
                if value.lower() in {"none", "off"}:
                    budget = None
                else:
                    budget = float(value.replace("$", "").replace(",", ""))
                    if budget <= 0:
                        raise ValueError("--budget must be positive or none")
            elif option == "--max-layover":
                max_layover = int(value)
                if not 60 <= max_layover <= 720:
                    raise ValueError("--max-layover must be 60 to 720 minutes")
            elif option == "--adults":
                values["adults"] = int(value)
                if not 1 <= values["adults"] <= 9: raise ValueError("--adults must be 1 to 9")
            elif option == "--cabin":
                values["cabin"] = Cabin(value.upper().replace("-", "_"))
            elif option == "--bags":
                values["checked_bags"] = int(value)
                if values["checked_bags"] not in {0, 1, 2}: raise ValueError("--bags must be 0, 1, or 2")
            elif option == "--carry-on":
                values["carry_on_bags"] = int(value)
                if values["carry_on_bags"] not in {0, 1, 2}: raise ValueError("--carry-on must be 0, 1, or 2")
            elif option == "--currency":
                values["currency"] = value.upper()
                if values["currency"] not in {"USD", "CAD", "EUR", "GBP", "INR"}: raise ValueError("unsupported currency")
            elif option == "--time":
                values["departure_window"] = DepartureWindow(value.lower())
            elif option == "--red-eye":
                if value.lower() not in {"avoid", "allow"}: raise ValueError("--red-eye must be avoid or allow")
                values["avoid_red_eye"] = value.lower() == "avoid"
            elif option == "--max-stops":
                values["max_stops"] = None if value.lower() in {"any", "none"} else int(value)
                if values["max_stops"] not in {None, 0, 1, 2}: raise ValueError("--max-stops must be 0, 1, 2, or any")
            elif option == "--min-layover":
                values["min_layover_minutes"] = int(value)
                if not 30 <= values["min_layover_minutes"] <= 180: raise ValueError("--min-layover must be 30 to 180")
            elif option == "--max-duration":
                values["max_total_duration_minutes"] = None if value.lower() in {"none", "any"} else int(value.lower().replace("h", "")) * 60
            elif option == "--timezone":
                try:
                    ZoneInfo(value)
                except ZoneInfoNotFoundError as exc:
                    raise ValueError("--timezone must be an IANA name such as America/New_York") from exc
                values["timezone"] = value
            else:
                quiet_match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", value)
                if not quiet_match:
                    raise ValueError("--quiet must look like 22-7")
                start_hour, end_hour = map(int, quiet_match.groups())
                if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23 or start_hour == end_hour:
                    raise ValueError("quiet hours must be different values from 0 to 23")
                values["quiet_start_hour"] = start_hour
                values["quiet_end_hour"] = end_hour
            index += 2
    except (ValueError, IndexError) as exc:
        await update.message.reply_text(f"Invalid profile update: {exc}")
        return
    if preferred.intersection(avoided):
        await update.message.reply_text(
            "The same airline cannot be both preferred and avoided."
        )
        return
    saved = await store.save_profile(
        user_id,
        UserProfile(preferred, avoided, budget, max_layover, **values),
    )
    await update.message.reply_text(
        _profile_text(saved)
        + "\n\nThese defaults apply to guided search, /flight, /quick, and the guided /watch wizard unless explicitly overridden. "
        "No RouteStack search token was used."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("trip", None)
    context.user_data.pop("pending_watch", None)
    context.user_data.pop("watch_form", None)
    context.user_data.pop("duplicate_watch_id", None)
    await update.message.reply_text(
        "Search cancelled. No flight search was made.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /search to start a flight search.")


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    logger.error(
        "Unhandled Telegram update error",
        exc_info=(
            type(context.error),
            context.error,
            context.error.__traceback__,
        )
        if context.error
        else None,
    )


async def on_shutdown(application: Application) -> None:
    client: RouteStackClient | None = application.bot_data.get("routestack")
    if client:
        await client.close()
    store: WatchStore | None = application.bot_data.get("watch_store")
    if store:
        await store.close()


def build_application(settings: Settings) -> Application:
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["routestack"] = RouteStackClient(settings)
    if settings.database_url:
        application.bot_data["watch_store"] = WatchStore(settings.database_url)

    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("search", begin_search),
            CommandHandler("flight", flight_command),
            CommandHandler("quick", quick_command),
            CommandHandler("repeat", repeat_command),
        ],
        states={
            ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, origin)],
            DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, destination)
            ],
            DEPARTURE: [
                CallbackQueryHandler(calendar_callback, pattern=r"^cal:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, departure),
            ],
            TRIP_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, trip_type)],
            RETURN: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_date)],
            PASSENGERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, passengers)
            ],
            CABIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, cabin)],
            CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, currency)],
            TIME_PREF: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_preference)],
            MAX_STOPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, max_stops)],
            RED_EYE: [MessageHandler(filters.TEXT & ~filters.COMMAND, red_eye)],
            CONNECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, connection_preference)],
            DURATION_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, duration_limit)],
            FLEXIBLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, flexible)],
            FLEX_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, flexible_days)
            ],
            NEARBY: [MessageHandler(filters.TEXT & ~filters.COMMAND, nearby)],
            BAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bags)],
            CARRY_ON: [MessageHandler(filters.TEXT & ~filters.COMMAND, carry_on)],
            AIRLINES: [MessageHandler(filters.TEXT & ~filters.COMMAND, airlines)],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget)],
            PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, priority)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    watch_conversation = ConversationHandler(
        entry_points=[CommandHandler("watch", watch_command)],
        states={
            WATCH_ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_origin)],
            WATCH_DESTINATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_destination)],
            WATCH_DEPARTURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_departure)],
            WATCH_TRIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_trip)],
            WATCH_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_duration)],
            WATCH_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_target)],
            WATCH_DROP: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_drop)],
            WATCH_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_interval)],
            WATCH_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_days)],
            WATCH_WEEKLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_weekly)],
            WATCH_CONFIRM: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, activate_watch
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(TypeHandler(Update, access_gate), group=-1)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("defaults", defaults_command))
    application.add_handler(CommandHandler("watches", watches_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("checknow", checknow_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("unwatch", unwatch_command))
    application.add_handler(CommandHandler("deals", deals_command))
    application.add_handler(CommandHandler("chart", chart_command))
    application.add_handler(CommandHandler("booked", booked_command))
    application.add_handler(CommandHandler("cleanup", cleanup_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("airports", airports_command))
    application.add_handler(CommandHandler("recent", recent_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(watch_conversation)
    application.add_handler(conversation)
    application.add_handler(
        CallbackQueryHandler(
            checkout_callback,
            pattern=r"^checkout:[A-Za-z0-9_-]{8}:\d+$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(watch_date_callback, pattern=r"^watchdate:(switch|both|keep):")
    )
    application.add_handler(
        CallbackQueryHandler(booked_callback, pattern=r"^booked:[0-9a-fA-F]{8}$")
    )
    application.add_handler(MessageHandler(filters.TEXT, unknown))
    application.add_error_handler(error_handler)
    return application
