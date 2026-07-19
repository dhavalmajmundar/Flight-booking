from __future__ import annotations

import logging
import re
import secrets
from datetime import date, timedelta

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
from .airports import is_domestic, local_airport
from .formatting import format_results, selected_results
from .links import expedia_search_url
from .models import Cabin, FlightOption, Priority, SearchRequest
from .ranking import rank_flights
from .routestack import FlightSearchError, RouteStackClient
from .watch_store import WatchStore
from .watching import (
    WATCH_CONFIRM,
    activate_watch,
    checknow_command,
    history_command,
    run_watch_cycle,
    unwatch_command,
    usage_command,
    watch_command,
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
    FLEXIBLE,
    NEARBY,
    BAGS,
    AIRLINES,
    BUDGET,
    PRIORITY,
    CONFIRM,
) = range(14)


def _keyboard(*rows: tuple[str, ...]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "I search and compare live flights only when you request one.\n\n"
        "Use /search for a guided search, /flight for one line, /watch for a "
        "private price alert, or /help for details."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Use /search and answer the guided questions. I will collect your route, "
        "dates, passengers, cabin, baggage, airline preferences, budget, and "
        "priority. No provider search happens until you confirm.\n\n"
        "Use /defaults to review the smart settings without making a search.\n\n"
        "Price-watch commands:\n"
        "/watch JFK LAX 2026-09-15 --return 2026-09-22 --target 350 "
        "--drop 5 --every 24 --for-days 30\n"
        "/watches — list alerts\n"
        "/history WATCH_ID — observed prices and guidance\n"
        "/checknow WATCH_ID — queue one token-capped check\n"
        "/unwatch WATCH_ID — stop an alert\n"
        "/usage — today's watch-token usage\n\n"
        "For a one-line request:\n"
        "/flight JFK LAX 2026-09-15\n\n"
        "Smart defaults: round trip returning after 7 nights, 1 adult, economy, "
        "flexible dates, nearby airports for domestic trips only, and automatic "
        "baggage (0 checked "
        "domestic; 2 checked + 1 carry-on international).\n\n"
        "Override with options such as --return 2026-09-20 --nights 5 "
        "--trip one-way --adults 2 --cabin business --flex no --nearby yes "
        "--bags 1 --carry-on 1 --prefer DL,UA --avoid NK,F9 --budget 1200 "
        "--priority balanced\n\n"
        "Airport codes such as JFK work best, but city or airport names are accepted."
    )


async def defaults_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.message.reply_text(
        "Smart defaults for /flight:\n"
        "• Round trip returning 7 days later\n"
        "• 1 adult in Economy\n"
        "• Flexible dates within ±3 days\n"
        "• Nearby airports: on domestic, off international\n"
        "• Domestic baggage: 0 checked + 1 carry-on\n"
        "• International baggage: 2 checked + 1 carry-on\n"
        "• Balanced ranking\n\n"
        "Before searching, choose the free suggested-date estimate or the full "
        "live ±3-day comparison. Use /help for every one-line override."
    )


BOT_COMMANDS = (
    BotCommand("start", "Open the flight assistant"),
    BotCommand("search", "Start a guided flight search"),
    BotCommand("flight", "Search in one line: JFK LAX 2026-09-15"),
    BotCommand("watch", "Create a recurring price alert"),
    BotCommand("watches", "List active price watches"),
    BotCommand("history", "Show observed watch prices"),
    BotCommand("checknow", "Queue one watch check"),
    BotCommand("usage", "Show today's watch token usage"),
    BotCommand("unwatch", "Stop a price watch"),
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
    context.user_data["trip"] = {}
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
        "origin": args[0],
        "destination": args[1],
        "departure_date": departure_value,
        "return_date": departure_value + timedelta(days=7),
        "adults": 1,
        "cabin": Cabin.ECONOMY,
        "flexible_dates": True,
        "nearby_airports": False,
        "auto_nearby": True,
        "checked_bags": 0,
        "carry_on_bags": 1,
        "auto_baggage": True,
        "preferred_airlines": set(),
        "avoided_airlines": set(),
        "max_budget": None,
        "priority": Priority.BALANCED,
    }
    value_options = {
        "--return",
        "--nights",
        "--trip",
        "--adults",
        "--cabin",
        "--flex",
        "--nearby",
        "--bags",
        "--carry-on",
        "--prefer",
        "--avoid",
        "--budget",
        "--priority",
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
        index += 2
    return trip


async def flight_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        trip = parse_flight_command(context.args)
    except ValueError as exc:
        await update.message.reply_text(
            f"Invalid flight command: {exc}\n\n"
            "Example:\n"
            "/flight JFK LAX 2026-09-15\n\n"
            "This defaults to a 7-night round trip, 1 adult, economy, flexible "
            "dates, domestic-only nearby airports, and smart baggage."
        )
        return ConversationHandler.END
    context.user_data["trip"] = trip
    return await show_confirmation(update, context)


async def origin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["trip"]["origin"] = update.message.text.strip()
    await update.message.reply_text("Where are you flying to?")
    return DESTINATION


async def destination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["trip"]["destination"] = update.message.text.strip()
    await update.message.reply_text(
        "Departure date? Use YYYY-MM-DD, for example 2026-09-15."
    )
    return DEPARTURE


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
        reply_markup=_keyboard(("One-way", "Round trip")),
    )
    return TRIP_TYPE


async def trip_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer not in {"one-way", "one way", "round trip", "round-trip"}:
        await update.message.reply_text("Choose One-way or Round trip.")
        return TRIP_TYPE
    if answer.startswith("one"):
        context.user_data["trip"]["return_date"] = None
        await update.message.reply_text(
            "How many adult passengers? (1–9)", reply_markup=ReplyKeyboardRemove()
        )
        return PASSENGERS
    await update.message.reply_text(
        "Return date? Use YYYY-MM-DD.", reply_markup=ReplyKeyboardRemove()
    )
    return RETURN


async def return_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parsed = _parse_future_date(update.message.text)
    departing = context.user_data["trip"]["departure_date"]
    if not parsed or parsed <= departing:
        await update.message.reply_text(
            "Return must be after departure. Send it as YYYY-MM-DD."
        )
        return RETURN
    context.user_data["trip"]["return_date"] = parsed
    await update.message.reply_text("How many adult passengers? (1–9)")
    return PASSENGERS


async def passengers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        count = int(update.message.text.strip())
    except ValueError:
        count = 0
    if not 1 <= count <= 9:
        await update.message.reply_text("Enter a number from 1 to 9.")
        return PASSENGERS
    context.user_data["trip"]["adults"] = count
    await update.message.reply_text(
        "Cabin class?",
        reply_markup=_keyboard(
            ("Economy", "Premium economy"), ("Business", "First")
        ),
    )
    return CABIN


async def cabin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = update.message.text.strip().lower().replace(" ", "_")
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
    await update.message.reply_text(
        "Search nearby dates within ±3 days? The trip length stays the same.",
        reply_markup=_keyboard(("Yes", "No")),
    )
    return FLEXIBLE


async def flexible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer not in {"yes", "no"}:
        await update.message.reply_text("Please choose Yes or No.")
        return FLEXIBLE
    context.user_data["trip"]["flexible_dates"] = answer == "yes"
    context.user_data["trip"]["nearby_airports"] = False
    context.user_data["trip"]["auto_nearby"] = True
    await update.message.reply_text(
        "Nearby airports will be included automatically for domestic trips and "
        "disabled for international trips.\n\n"
        "How many checked bags must be included per traveler? (0–2)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return BAGS


async def nearby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer not in {"yes", "no"}:
        await update.message.reply_text("Please choose Yes or No.")
        return NEARBY
    context.user_data["trip"]["nearby_airports"] = answer == "yes"
    context.user_data["trip"]["auto_nearby"] = False
    await update.message.reply_text(
        "How many checked bags must be included per traveler? (0–2)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return BAGS


async def bags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        count = int(update.message.text.strip())
    except ValueError:
        count = -1
    if count not in {0, 1, 2}:
        await update.message.reply_text("Enter 0, 1, or 2.")
        return BAGS
    context.user_data["trip"]["checked_bags"] = count
    context.user_data["trip"]["carry_on_bags"] = 1
    context.user_data["trip"]["auto_baggage"] = False
    await update.message.reply_text(
        "Airline preferences? Use IATA codes like:\n"
        "prefer: DL,UA; avoid: F9,NK\n\n"
        "Or send “none”."
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
    parsed = _parse_airlines(update.message.text)
    if parsed is None:
        await update.message.reply_text(
            "Use “none” or this format: prefer: DL,UA; avoid: F9,NK"
        )
        return AIRLINES
    preferred, avoided = parsed
    context.user_data["trip"]["preferred_airlines"] = preferred
    context.user_data["trip"]["avoided_airlines"] = avoided
    await update.message.reply_text(
        "Maximum total budget in USD for everyone? Send a number or “none”."
    )
    return BUDGET


async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower().replace("$", "").replace(",", "")
    if answer in {"none", "no", "n/a"}:
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
    await update.message.reply_text(
        "What should I optimize for?",
        reply_markup=_keyboard(
            ("Balanced", "Cheapest"), ("Fastest", "Nonstop")
        ),
    )
    return PRIORITY


async def priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
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
        f"${trip['max_budget']:,.2f}" if trip["max_budget"] else "no maximum"
    )
    nearby_search_allowance = _nearby_search_allowance(trip)
    maximum_provider_calls = (
        7 if trip["flexible_dates"] else 1
    ) + nearby_search_allowance
    nearby_text = (
        "smart: yes domestic; no international"
        if trip.get("auto_nearby")
        else ("yes" if trip["nearby_airports"] else "no")
    )
    baggage_text = (
        "smart: 0 checked domestic; 2 checked + 1 carry-on international"
        if trip.get("auto_baggage")
        else (
            f"{trip['checked_bags']} checked + "
            f"{trip.get('carry_on_bags', 1)} carry-on each"
        )
    )
    date_advice = ""
    confirmation_buttons: tuple[str, ...]
    if trip["flexible_dates"]:
        suggested = suggested_departure_date(trip["departure_date"])
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
            "Search suggested date",
            "Compare all ±3 days",
            "Cancel",
        )
    else:
        confirmation_buttons = ("Search now", "Cancel")
    usage_label = (
        "Full flexible comparison"
        if trip["flexible_dates"]
        else "Planned search"
    )

    await update.message.reply_text(
        "Please confirm:\n"
        f"{trip['origin']} → {trip['destination']}\n"
        f"Depart: {trip['departure_date']} | Return: {return_text}\n"
        f"{trip['adults']} adult(s) | {trip['cabin'].value.replace('_', ' ').title()}\n"
        f"Flexible: {'yes, ±3 days' if trip['flexible_dates'] else 'no'} | "
        f"Nearby airports: {nearby_text} | "
        f"Baggage: {baggage_text}\n"
        f"Budget: {budget_text} | Priority: {trip['priority'].value}\n\n"
        f"{usage_label}: up to {maximum_provider_calls} "
        f"RouteStack search token(s).\n"
        f"{date_advice}\n"
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


def suggested_departure_date(departure: date) -> date:
    """Choose a no-call weekday candidate within ±3 days.

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
        for shift in range(-3, 4)
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
    if answer == "search suggested date" and trip["flexible_dates"]:
        suggested = trip.pop("suggested_departure_date")
        shift = suggested - trip["departure_date"]
        trip["departure_date"] = suggested
        if trip["return_date"]:
            trip["return_date"] += shift
        trip["flexible_dates"] = False
    elif answer == "compare all ±3 days" and trip["flexible_dates"]:
        trip.pop("suggested_departure_date", None)
    elif answer == "search now":
        trip.pop("suggested_departure_date", None)
    else:
        await update.message.reply_text(
            "Choose Search suggested date, Compare all ±3 days, or Cancel."
            if trip["flexible_dates"]
            else "Choose Search now or Cancel."
        )
        return CONFIRM

    await update.message.reply_text(
        "Searching live fares and comparing the best options…",
        reply_markup=ReplyKeyboardRemove(),
    )
    settings: Settings = context.application.bot_data["settings"]
    request = SearchRequest(currency=settings.default_currency, **trip)
    client: RouteStackClient = context.application.bot_data["routestack"]
    try:
        offers, origin_label, destination_label = await client.search(request)
        results = rank_flights(offers, request)
        if not results:
            await update.message.reply_text(
                "No matching live offers were returned. Try nearby dates, a higher "
                "budget, fewer baggage restrictions, or nearby airports."
            )
        else:
            message = format_results(
                results, request, origin_label, destination_label
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
    return InlineKeyboardMarkup(
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
            for rank, option in enumerate(options, 1)
        ]
    )


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
                        )
                    ]
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
                    )
                ],
            ]
        ),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("trip", None)
    context.user_data.pop("pending_watch", None)
    await update.message.reply_text(
        "Search cancelled. No flight search was made.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /search to start a flight search.")


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
        ],
        states={
            ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, origin)],
            DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, destination)
            ],
            DEPARTURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, departure)],
            TRIP_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, trip_type)],
            RETURN: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_date)],
            PASSENGERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, passengers)
            ],
            CABIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, cabin)],
            FLEXIBLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, flexible)],
            NEARBY: [MessageHandler(filters.TEXT & ~filters.COMMAND, nearby)],
            BAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bags)],
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
    application.add_handler(watch_conversation)
    application.add_handler(conversation)
    application.add_handler(
        CallbackQueryHandler(
            checkout_callback,
            pattern=r"^checkout:[A-Za-z0-9_-]{8}:\d+$",
        )
    )
    application.add_handler(MessageHandler(filters.TEXT, unknown))
    return application
