from __future__ import annotations

import logging
import re
from datetime import date

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .config import Settings
from .formatting import format_results
from .models import Cabin, Priority, SearchRequest
from .ranking import rank_flights
from .routestack import FlightSearchError, RouteStackClient

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
        "Use /search to start, /cancel to stop, or /help for details."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Use /search and answer the guided questions. I will collect your route, "
        "dates, passengers, cabin, baggage, airline preferences, budget, and "
        "priority. No provider search happens until you confirm.\n\n"
        "Airport codes such as JFK work best, but city or airport names are accepted."
    )


async def begin_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["trip"] = {}
    await update.message.reply_text(
        "Where are you departing from? Send a city, airport, or 3-letter code.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ORIGIN


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
    await update.message.reply_text(
        "Also compare nearby departure or arrival airports (within about 100 km)?",
        reply_markup=_keyboard(("Yes", "No")),
    )
    return NEARBY


async def nearby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer not in {"yes", "no"}:
        await update.message.reply_text("Please choose Yes or No.")
        return NEARBY
    context.user_data["trip"]["nearby_airports"] = answer == "yes"
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
    trip = context.user_data["trip"]
    return_text = (
        trip["return_date"].isoformat() if trip["return_date"] else "one-way"
    )
    budget_text = (
        f"${trip['max_budget']:,.2f}" if trip["max_budget"] else "no maximum"
    )
    maximum_provider_calls = (7 if trip["flexible_dates"] else 1) + (
        4 if trip["nearby_airports"] else 0
    )
    await update.message.reply_text(
        "Please confirm:\n"
        f"{trip['origin']} → {trip['destination']}\n"
        f"Depart: {trip['departure_date']} | Return: {return_text}\n"
        f"{trip['adults']} adult(s) | {trip['cabin'].value.replace('_', ' ').title()}\n"
        f"Flexible: {'yes, ±3 days' if trip['flexible_dates'] else 'no'} | "
        f"Nearby airports: {'yes' if trip['nearby_airports'] else 'no'} | "
        f"Checked bags: {trip['checked_bags']} each\n"
        f"Budget: {budget_text} | Priority: {selected.value}\n\n"
        f"RouteStack usage: up to {maximum_provider_calls} search token(s).\n\n"
        "Search live fares now?",
        reply_markup=_keyboard(("Search now", "Cancel")),
    )
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer == "cancel":
        return await cancel(update, context)
    if answer != "search now":
        await update.message.reply_text("Choose Search now or Cancel.")
        return CONFIRM

    await update.message.reply_text(
        "Searching live fares and comparing the best options…",
        reply_markup=ReplyKeyboardRemove(),
    )
    trip = context.user_data["trip"]
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


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("trip", None)
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


def build_application(settings: Settings) -> Application:
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["routestack"] = RouteStackClient(settings)

    conversation = ConversationHandler(
        entry_points=[CommandHandler("search", begin_search)],
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
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(conversation)
    application.add_handler(MessageHandler(filters.TEXT, unknown))
    return application
