# On-demand Telegram Flight Bot

A Telegram bot that collects trip preferences, asks for confirmation, then searches
live RouteStack flight offers. It ranks results by price, travel time, stops, baggage,
airline preferences, and the user's chosen priority.

The bot does **not** search in the background and does **not** invent prices.

## Features

- Guided `/search` conversation
- Button-driven guided setup with an inline start-date calendar, one-way/round-
  trip selection, common trip durations, passenger counts, flexible range,
  nearby-airport policy, baggage defaults, cabin, and optimization choices
- Telegram slash-command menu registered automatically at startup
- `/defaults` helper describing the smart settings without making a fare call
- Owner-only access gate that stops unauthorized messages and callbacks before
  any RouteStack-capable handler
- Credential-redacting log formatter and suppressed HTTP request logging so
  Telegram, RouteStack, and database secrets do not appear in deployment logs
- Persistent Railway Postgres price watches with target, percentage-drop, and
  new-record-low alerts
- Daily watch-token cap, automatic pausing, price history, daily digests, weekly
  summaries, expiry reminders, and observed-history book/wait guidance
- One-line `/flight` command with optional filters
- Smart progressive search that starts with one suggested date, expands to ±3
  days only when needed, and checks eligible domestic nearby airports last
- Smart `/flight` defaults: 7-night round trip, four adults, economy, flexible
  dates, nearby airports for domestic routes only, 2 checked bags, and 1 carry-on
- Local IATA airport/country resolution to avoid provider calls for exact codes
- Five-minute identical-search cache with checkout-time fare revalidation
- One-way and round-trip searches
- Economy, premium economy, business, and first class
- Selectable ±1 to ±7-day flexible-date comparison (default ±3) while
  preserving trip length
- Top-three booking handoff buttons for the best overall, cheapest, and fastest
  distinct recommendations
- Live revalidation before RouteStack generates a secure external checkout link
- Expedia comparison deeplinks for the same route, travel dates, passengers,
  cabin, and single operating airline when available
- Privacy-conscious click events in Railway logs for measuring popular routes
- Optional nearby-airport comparison within roughly 100 km
- Separate checked-bag and carry-on choices, airline avoidance, preset/custom
  budgets, and clearly explained ranking preferences
- Best overall, cheapest, fastest, and flexible-date picks
- Prominent, non-blocking warnings and ranking penalties for self-transfers,
  airport changes, overnight connections, tight/long layovers, multiple stops,
  and very long itineraries
- Google Flights and Kayak comparison links alongside Expedia and exact
  RouteStack checkout; comparison-link creation uses no RouteStack search token
- Local `/airports CITY, STATE` helper and guided airport-choice buttons
- Postgres-backed `/profile`, `/recent`, and `/repeat` helpers
- Route-history deal labels based only on fares this bot previously observed
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
value into Railway, and redeploy. After configuration, `/myid` also responds
only to the owner. Unauthorized users are stopped before search, checkout, or
watch handlers and therefore cannot consume RouteStack tokens.

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

Watch scheduling is urgency-aware while remaining inside the same global daily
cap. It checks less often when departure is far away, then may increase frequency
near departure or when the observed fare approaches the target. Due watches
closest to their targets and travel dates are considered first. Alerts keep
cheaper risky itineraries visible, identify quality tradeoffs, and call out when
an affordable nonstop becomes available.

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

Airport codes are optional. For multi-word cities, states, or full airport names,
separate the three required fields with `|`:

```text
/flight New York, NY | Los Angeles, CA | 2026-09-15
/watch New York, NY | Los Angeles, CA | 2026-09-15 --return 2026-09-22 --target 350
```

Single-word cities continue to work in the normal space-separated format.

That command defaults to a round trip returning seven days later, four adults,
economy, flexible dates within ±3 days, domestic-only nearby airports, and
balanced ranking.
The normal baggage default is 2 checked bags plus 1 carry-on per traveler.
`--bags auto` instead requests 0 checked bags domestically or 2 internationally;
the carry-on choice remains independently configurable.

The guided `/search` flow uses the same automatic nearby-airport rule without
asking an additional question: enabled domestically and disabled internationally.

For all supported one-line options:

```text
/flight JFK LAX 2026-09-15 --return 2026-09-20 --adults 2 --cabin economy --flex yes --nearby no --bags 1 --carry-on 1 --prefer DL,UA --avoid NK,F9 --budget 1200 --priority balanced
```

Use `--nights 5` for a five-night round trip, `--trip one-way` for one-way,
`--nearby yes|no|auto` to override nearby-airport behavior, or `--bags auto`
to restore route-aware baggage after a manual override. Use `--flex-days 1..7`
to choose the live comparison window.

The guided `/search` flow only normally requires typing the origin and
destination. It provides an inline calendar for the start date and reply buttons
for one-way/round trip, common trip durations, 1–9 passengers (4 is marked as the
default), cabin, flexible yes/no, ±1/2/3/5/7 days, nearby airports, 0/1/2 checked
bags (2 default), 0/1/2 carry-ons (1 default), no airline preference, common
route/cabin/passenger-aware maximum budgets, a custom amount, or no maximum,
and ranking priority. Nearby `Auto`
means on for domestic trips and off for international trips.

Ranking priority changes ordering, not which live fares are returned: `Balanced`
uses price, duration, and stops; `Cheapest` emphasizes fare; `Fastest` emphasizes
total travel time; and `Nonstop` strongly favors zero-stop itineraries. Safety
warnings remain visible in every mode.

Budget buttons are planning limits rather than price forecasts. Domestic bands
are anchored to the latest available public benchmarks: BTS reported a $428
average U.S. domestic itinerary fare for Q1 2026, while ARC reported December
2025 domestic averages of $514 for economy and $1,370 for premium tickets.
Buttons scale those anchors by passenger count, cabin, and trip type. International
buttons use wider planning bands because route variation is much larger. The bot
does not call RouteStack to generate these buttons, and `Custom amount` accepts
any positive USD total. Optional baggage and seat fees may not be in the fare
budget. Sources: [BTS Air Fares](https://www.bts.gov/air-fares) and
[ARC 2025 ticket sales](https://www2.arccorp.com/about-us/newsroom/2026-news-releases/december-2025-air-ticket-sales/).

The bot still asks for confirmation before spending RouteStack search tokens.
When flexible dates are enabled, that confirmation first shows a free calendar
estimate favoring Monday–Wednesday departures within the selected range. Users
can search
only that suggested date, choose smart progressive search, or choose the complete
live comparison. Progressive mode stops after one call when it finds a usable
low-risk result; otherwise it expands to nearby dates and finally eligible
domestic nearby airports. The estimate is a broad historical pattern, not a live
price claim.

## Free helpers and saved preferences

These commands do not call RouteStack's flight-search endpoint:

```text
/airports New York, NY
/recent
/repeat 1
/profile
/profile --prefer DL,UA --avoid NK,F9 --budget 900 --max-layover 240
/profile --clear
```

`/airports` uses the bundled airport database. During guided `/search`, ambiguous
city input presents airport choices before the confirmation screen. One-line
city/state searches show likely local codes at confirmation; using a three-letter
code remains the most precise choice.

Successful searches are retained in Postgres as a bounded recent list. `/repeat`
loads a previous request and still requires confirmation before any live call.
The profile supplies defaults to `/flight` unless the command explicitly
overrides them. Historical deal labels compare only with this bot's saved results
for the same resolved route and currency; they are not market-wide predictions.

## Booking handoff

The bot never collects passenger or payment details and never issues a ticket.
After a search, users can choose one of the top three options. The bot revalidates
that offer with RouteStack and returns a signed RouteStack hosted-checkout link.
The final price, baggage allowance, and change/cancellation rules must be reviewed
there before payment.

Each top option also has an Expedia comparison button built from Expedia's
documented flight deeplink format, plus Google Flights and Kayak search links.
RouteStack is the revalidated selected offer; comparison sites perform separate
searches and may show a different itinerary, baggage allowance, or price. No
affiliate or price-match claim is made, and opening/building those comparison
links does not spend RouteStack search tokens.

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

- Flexible-date mode makes `2 × flexible days + 1` provider searches: seven at
  the ±3 default, from three days earlier through three days later.
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
- Progressive mode reuses the five-minute cache between stages. A suggested date
  already searched in stage one is not billed again when the bot expands to the
  seven-date window.
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
