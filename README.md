# On-demand Telegram Flight Bot

A Telegram bot that collects trip preferences, asks for confirmation, then searches
live RouteStack flight offers. It ranks results by price, travel time, stops, baggage,
airline preferences, and the user's chosen priority.

The bot does **not** search in the background and does **not** invent prices.

## Features

- Guided `/search` conversation
- One-line `/flight` command with optional filters
- One-way and round-trip searches
- Economy, premium economy, business, and first class
- Optional ±3-day flexible-date comparison while preserving trip length
- Top-three booking handoff buttons for the best overall, cheapest, and fastest
  distinct recommendations
- Live revalidation before RouteStack generates a secure external checkout link
- Privacy-conscious click events in Railway logs for measuring popular routes
- Optional nearby-airport comparison within roughly 100 km
- Checked-bag, airline avoidance, budget, and optimization preferences
- Best overall, cheapest, fastest, and flexible-date picks
- Transparent warnings when baggage or fare conditions need verification
- Long polling, so no public webhook is required

## Prerequisites

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A RouteStack partner API key and secret

RouteStack determines sandbox versus production access from the credentials. The
default base URL is its public MCP/HTTP endpoint.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Fill in `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=...
ROUTESTACK_API_KEY=...
ROUTESTACK_API_SECRET=...
ROUTESTACK_BASE_URL=https://mcp.routestack.ai
DEFAULT_CURRENCY=USD
MAX_RESULTS=40
```

Run:

```powershell
python -m flight_bot.main
```

Then open the bot in Telegram and send `/start` or `/search`.

For a minimal one-line search:

```text
/flight JFK LAX 2026-09-15
```

For all supported one-line options:

```text
/flight JFK LAX 2026-09-15 --return 2026-09-20 --adults 2 --cabin economy --flex yes --nearby no --bags 1 --prefer DL,UA --avoid NK,F9 --budget 1200 --priority balanced
```

The bot still asks for confirmation before spending RouteStack search tokens.

## Booking handoff

The bot never collects passenger or payment details and never issues a ticket.
After a search, users can choose one of the top three options. The bot revalidates
that offer with RouteStack and returns a signed RouteStack hosted-checkout link.
The final price, baggage allowance, and change/cancellation rules must be reviewed
there before payment.

Each handoff click writes an aggregate-friendly event to the application log with
the route, result rank, and source. It deliberately does not log the Telegram user
ID, passenger details, fare identifier, or checkout URL. In Railway, search the
deployment logs for `booking_handoff_clicked` to see demand by route.

## Tests

```powershell
pytest
```

## Deployment

This service can run on any always-on Python host. Configure the same environment
variables and use this start command:

```text
python -m flight_bot.main
```

Only one polling instance should run for a bot token. If you later switch to a
webhook deployment, remove polling and configure a public HTTPS endpoint.

Or build and run the included container:

```powershell
docker build -t flight-bot .
docker run --env-file .env --restart unless-stopped flight-bot
```

## Data and pricing notes

- Flexible-date mode makes up to seven provider searches: the requested dates and
  matching trip-length shifts from three days earlier through three days later.
- Nearby-airport mode checks up to two alternatives at each end on the requested
  dates. It deliberately avoids a large date × airport combination search.
- RouteStack prices one completed search as one token. Combining flexible dates
  and nearby airports can therefore use up to 11 tokens for one Telegram request;
  the confirmation screen shows this maximum before searching.
- The total shown is RouteStack's first available display/total fare field.
- Checked-bag metadata is provider-reported and sometimes absent.
- Cancellation, changes, seat selection, payment-card fees, and exact baggage
  terms may not be included in flight search. The bot tells users to verify
  those terms at checkout.
- Airline “reliability” is not guessed. Add a licensed on-time-performance source
  before ranking on that factor.
