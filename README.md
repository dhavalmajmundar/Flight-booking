# On-demand Telegram Flight Bot

A Telegram bot that collects trip preferences, asks for confirmation, then searches
live RouteStack flight offers. It ranks results by price, travel time, stops, baggage,
airline preferences, and the user's chosen priority.

The bot does **not** search in the background and does **not** invent prices.

## Features

- Guided `/search` conversation
- Telegram slash-command menu registered automatically at startup
- `/defaults` helper describing the smart settings without making a fare call
- Owner-only access gate that stops unauthorized messages and callbacks before
  any RouteStack-capable handler
- Persistent Railway Postgres price watches with target, percentage-drop, and
  new-record-low alerts
- Daily watch-token cap, automatic pausing, price history, daily digests, weekly
  summaries, expiry reminders, and observed-history book/wait guidance
- One-line `/flight` command with optional filters
- Smart `/flight` defaults: 7-night round trip, one adult, economy, flexible
  dates, nearby airports for domestic routes only, and route-aware baggage
- Local IATA airport/country resolution to avoid provider calls for exact codes
- Five-minute identical-search cache with checkout-time fare revalidation
- One-way and round-trip searches
- Economy, premium economy, business, and first class
- Optional ±3-day flexible-date comparison while preserving trip length
- Top-three booking handoff buttons for the best overall, cheapest, and fastest
  distinct recommendations
- Live revalidation before RouteStack generates a secure external checkout link
- Expedia comparison deeplinks for the same route, travel dates, passengers,
  cabin, and single operating airline when available
- Privacy-conscious click events in Railway logs for measuring popular routes
- Optional nearby-airport comparison within roughly 100 km
- Checked-bag, airline avoidance, budget, and optimization preferences
- Best overall, cheapest, fastest, and flexible-date picks
- Cheapest departure-day table across the live ±3-day search, including savings
  versus the requested date
- No-call calendar estimate before confirmation, with a choice between one
  suggested-date search and the accurate seven-date live comparison
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
SEARCH_CACHE_SECONDS=300
OWNER_TELEGRAM_USER_ID=123456789
DATABASE_URL=postgresql://...
WATCH_DAILY_TOKEN_CAP=10
WATCH_MAX_ACTIVE=5
WATCH_MAX_DAYS=60
WATCH_DIGEST_HOUR_UTC=13
```

`OWNER_TELEGRAM_USER_ID` is the only account allowed to use the bot. If it is
unset, every command is locked except `/myid`. Send `/myid`, copy the numeric
value into Railway, and redeploy. Unauthorized users are stopped before search,
checkout, or watch handlers and therefore cannot consume RouteStack tokens.

For persistent watches, add a Railway PostgreSQL service and expose its
`DATABASE_URL` to the bot service. Without it, normal owner searches work but
watch commands remain disabled.

Run:

```powershell
python -m flight_bot.main
```

Then open the bot in Telegram and send `/start` or `/search`.
Typing `/` shows the registered command menu after the deployment has restarted.

## Price watches

Create a safe-default watch:

```text
/watch JFK LAX 2026-09-15 --return 2026-09-22 --target 350
```

Full example:

```text
/watch JFK LAX 2026-09-15 --return 2026-09-22 --target 350 --drop 5 --every 24 --for-days 30 --cabin economy --prefer DL,UA
```

Watch commands:

- `/watches` lists active watches.
- `/history WATCH_ID` shows up to 60 days of observed history and guidance.
- `/checknow WATCH_ID` queues one additional token-capped check.
- `/unwatch WATCH_ID` stops a watch.
- `/usage` shows today's watch-token attempts and the configured cap.

Safe defaults are one exact route/date search every 24 hours, a 5% meaningful
drop threshold, at most five active watches, and at most 60 days. Flexible dates
and nearby airports are disabled for recurring checks, so each check attempts no
more than one RouteStack search token. The confirmation shows the maximum
lifetime usage before activation. The global daily cap defaults to 10; remaining
checks pause until the next UTC day when it is reached.

The first successful check sends a baseline. Later alerts are sent for a target
price, a configured percentage reduction, or a new record low, without repeating
the same alert price. Each observation is stored in Postgres. Daily digests,
Monday weekly summaries, and 48-hour expiry reminders are automatic. “Book now”
or “wait” language uses only that watch's recorded history; it is not a market
forecast. Alerts include an exact RouteStack revalidation button and an Expedia
comparison link.

For a minimal one-line search:

```text
/flight JFK LAX 2026-09-15
```

That command defaults to a round trip returning seven days later, one adult,
economy, flexible dates within ±3 days, domestic-only nearby airports, and
balanced ranking.
Smart baggage requests 0 checked bags for domestic trips or 2 checked bags plus
1 carry-on for international trips.

The guided `/search` flow uses the same automatic nearby-airport rule without
asking an additional question: enabled domestically and disabled internationally.

For all supported one-line options:

```text
/flight JFK LAX 2026-09-15 --return 2026-09-20 --adults 2 --cabin economy --flex yes --nearby no --bags 1 --carry-on 1 --prefer DL,UA --avoid NK,F9 --budget 1200 --priority balanced
```

Use `--nights 5` for a five-night round trip, `--trip one-way` for one-way,
`--nearby yes|no|auto` to override nearby-airport behavior, or `--bags auto`
to restore route-aware baggage after a manual override.

The bot still asks for confirmation before spending RouteStack search tokens.
When flexible dates are enabled, that confirmation first shows a free calendar
estimate favoring Monday–Wednesday departures within ±3 days. Users can search
only that suggested date to reduce provider usage or choose the complete live
comparison. The estimate is a broad historical pattern, not a live price claim.

## Booking handoff

The bot never collects passenger or payment details and never issues a ticket.
After a search, users can choose one of the top three options. The bot revalidates
that offer with RouteStack and returns a signed RouteStack hosted-checkout link.
The final price, baggage allowance, and change/cancellation rules must be reviewed
there before payment.

Each top option also has an Expedia comparison button built from Expedia's
documented flight deeplink format. RouteStack is the revalidated selected offer;
Expedia performs a separate search and may show a different itinerary, baggage
allowance, or price. No affiliate or price-match claim is made.

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
- Those same results produce the cheapest travel-day table, so this comparison
  does not add provider calls. It compares departure dates rather than claiming
  there is a universal best weekday to purchase airfare.
- The pre-search calendar estimate follows Google's 2025 aggregated finding that
  Monday–Wednesday travel averaged less than weekend departures for trips from
  U.S. airports. It is clearly labeled as an estimate because only live inventory
  can establish the cheapest date for a specific route.
- Exact three-letter airport codes are resolved from a bundled local database,
  avoiding RouteStack location calls. City codes and names fall back to RouteStack.
- Identical date/route searches are cached for five minutes. Cached results are
  labeled, and a selected fare is always revalidated before checkout.
- Nearby-airport mode checks up to two alternatives at each end on the requested
  dates. It deliberately avoids a large date × airport combination search.
- RouteStack prices one completed search as one token. Combining flexible dates
  and nearby airports can therefore use up to 11 tokens for one Telegram request;
  the confirmation screen shows this maximum before searching.
- Watch usage is counted conservatively as attempted searches before the provider
  response. RouteStack describes its production model as one successful search
  per token; the conservative local count prevents accidental overspending.
- The total shown is RouteStack's first available display/total fare field.
- Checked-bag metadata is provider-reported and sometimes absent.
- Cancellation, changes, seat selection, payment-card fees, and exact baggage
  terms may not be included in flight search. The bot tells users to verify
  those terms at checkout.
- Airline “reliability” is not guessed. Add a licensed on-time-performance source
  before ranking on that factor.
