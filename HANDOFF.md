# Flight Bot Handoff

Last updated: 2026-07-22

## Current status

- Repository: `dhavalmajmundar/Flight-booking`
- Production branch: `main`
- Hosting: Railway, connected to GitHub for automatic deployments
- Runtime: Python Telegram bot using long polling
- Flight provider: RouteStack
- Handoff policy: update this file in every completed change; use `git log -1`
  for the commit containing the latest handoff
- Verification: 45 automated tests passing

## User experience

- `/search` starts the guided search.
- Guided search uses an inline month calendar for the start date and reply
  buttons for trip type, round-trip duration, 1–9 passengers, cabin, flexibility,
  ±1/2/3/5/7 flexible days, nearby-airport behavior, separate checked/carry-on
  baggage, budget presets, skip choices, and ranking. Only origin/destination
  normally require typing.
- `/flight ORIGIN DESTINATION YYYY-MM-DD` starts a one-line search.
- Multi-word cities, states, and airport names use pipe separators, for example
  `/flight New York, NY | Los Angeles, CA | 2026-09-15`. The same format works
  for `/watch`.
- `/defaults` explains the smart defaults without using RouteStack.
- `/watch` creates a persistent price alert after showing estimated maximum
  lifetime usage and requiring confirmation.
- `/watches`, `/history`, `/checknow`, `/unwatch`, and `/usage` manage watches.
- The bot registers all 17 owner commands with Telegram during startup so typing
  `/` displays searches, watches, airport, history, profile, recent/repeat, and
  support helpers.
- One-line defaults:
  - Round trip, returning seven days later
  - Four adults
  - Economy
  - Flexible dates within ±3 days; selectable from ±1 to ±7
  - Nearby airports enabled domestically and disabled internationally
  - Baggage: 2 checked bags and 1 carry-on per traveler
  - Optional smart checked bags: 0 domestic or 2 international, while carry-on
    remains independently selectable
  - Balanced ranking
- Before any RouteStack fare call, the bot shows a free calendar estimate based
  on broad historical Monday–Wednesday travel trends.
- The user then chooses:
  - Smart progressive search (one suggested date, then dates, then eligible
    domestic nearby airports only when earlier stages remain missing or risky)
  - Search only the suggested date
  - Compare all dates within the selected ±1 to ±7-day range
  - Cancel without making a fare call
- The full comparison shows the cheapest live departure day and savings versus
  the requested date.
- Results identify best overall, cheapest, fastest, and flexible-date options.
- Up to three distinct results can be revalidated and opened in RouteStack's
  hosted checkout.
- Each top result also provides an Expedia comparison search for the same route,
  option dates, passenger count, cabin, and airline when a single code is known.
- RouteStack is labeled as the exact revalidated offer. Expedia is labeled as a
  separate comparison whose itinerary and price may differ. Google Flights and
  Kayak comparison links are also provided and do not use RouteStack tokens.
- Unsafe itineraries are never silently filtered. Self-transfers, airport
  changes, overnight/tight/long connections, multiple stops, and very long legs
  remain visible with prominent warnings and ranking penalties.
- Guided city input presents local airport choices; `/airports` lists likely
  codes without a provider call.
- `/profile` persists one-line airline, budget, and maximum-layover defaults.
  `/recent` and `/repeat` reuse successful searches but still require live-search
  confirmation.
- Deal labels use only Postgres history observed by this bot for the resolved
  route and currency.
- Ranking choices appear in this order: Cheapest, Balanced, Fastest, Nonstop.
  The prompt explains price-first, balanced price/time/stops, fastest-first, and
  strong nonstop preference. They reorder offers without hiding safety warnings.
- Budget buttons are generated locally from route type, cabin, one-way/round-trip,
  and passenger count. Domestic anchors reference BTS Q1 2026 ($428 average
  itinerary) and ARC December 2025 ($514 economy/$1,370 premium); international
  values are deliberately wider planning bands. `Custom amount` waits for any
  positive USD total. No RouteStack call is used to create budget choices.
- Telegram never collects payment details or issues tickets.

## Security and ownership

- `OWNER_TELEGRAM_USER_ID` is the only account permitted to use the bot.
- A group `-1` update gate runs before every message and callback handler.
- Unauthorized updates terminate before any RouteStack-capable code.
- When no owner ID is configured, only `/myid` works; all searches are locked.
- `/myid` never calls RouteStack and is used to obtain the ID for Railway. Once
  the owner is configured, it responds only to that owner.
- Only one Railway bot instance should run to preserve the strict global watch
  cap and Telegram long-polling ownership.
- Application logging redacts the Telegram token, RouteStack credentials, and
  database URL. HTTPX/HTTPCore request logging stays at WARNING because Telegram
  embeds the bot token in Bot API request URLs.

## Persistent price watches

- Railway PostgreSQL is required through `DATABASE_URL`.
- Watches default to one exact route/date search and a 24-hour base interval.
- Scheduling conserves calls far from departure, becomes more frequent near
  departure or a target price, and prioritizes urgent due watches within the
  unchanged global daily cap.
- Flexible dates and nearby airports are disabled for recurring checks.
- Defaults: 5% drop alert, five active watches, 60-day maximum, and ten attempted
  watch searches per UTC day globally.
- The first result establishes a baseline. Alerts trigger on target price,
  meaningful drop, or a non-duplicated record low.
- Postgres stores observed price, airline, duration, stops, and timestamps.
- Automated output includes daily digests, Monday weekly summaries, 48-hour
  expiry reminders, and guidance based only on observed watch history.
- At the daily cap, due checks move to the next UTC day and the owner is notified.
- RouteStack revalidation remains click-only; scheduled jobs never generate
  checkout links or collect payment details.
- Alerts disclose itinerary risks and quality regressions and separately identify
  newly affordable nonstop options.

## API-usage safeguards

- Exact IATA airport codes are resolved from the local `airportsdata` package.
- City names and unsupported city codes fall back to RouteStack location lookup.
- International searches do not request nearby-airport alternatives by default.
- Identical individual fare searches are cached in memory for five minutes.
- Overlapping flexible-date searches can reuse cached date results.
- Progressive stages share that cache, preventing the first date from being
  searched twice when the bot expands.
- Flexible search usage is calculated dynamically as `2 × days + 1`, plus any
  eligible nearby-airport searches; confirmation shows that maximum.
- Cached offers are labeled and always revalidated before checkout.
- Confirmation screens disclose the maximum possible RouteStack search calls.

## Important files

- `flight_bot/bot.py`: Telegram commands, conversations, confirmation, checkout
- `flight_bot/routestack.py`: authentication, location resolution, search cache,
  offer parsing, revalidation, and checkout links
- `flight_bot/ranking.py`: price/time/stop ranking and cheapest-date calculation
- `flight_bot/formatting.py`: Telegram result presentation
- `flight_bot/links.py`: documented external comparison deeplinks
- `flight_bot/airports.py`: local airport and country helpers
- `flight_bot/config.py`: environment configuration
- `flight_bot/command_input.py`: normal and multi-word command parsing
- `flight_bot/watch_store.py`: PostgreSQL schema and persistent watch operations
- `flight_bot/watching.py`: watch commands, scheduler, alerts, digests, and caps
- `tests/`: automated regression tests

## Required environment variables

- `TELEGRAM_BOT_TOKEN`
- `ROUTESTACK_API_KEY`
- `ROUTESTACK_API_SECRET`
- `OWNER_TELEGRAM_USER_ID` (required to unlock bot use)

`DATABASE_URL` is required for watches. Other optional watch limits are documented
in `.env.example`. Never commit `.env`,
Telegram credentials, RouteStack secrets, fare identifiers, or checkout URLs.

## Verification and deployment

Run:

```powershell
python -m pip install -e ".[dev]"
python -m compileall -q flight_bot tests
python -m pytest -q
```

After every completed update:

1. Update this file with the changed behavior, test count, and latest commit context.
2. Commit all scoped changes.
3. Push to `origin main`.
4. Report the commit ID and expected Railway redeployment.

Railway should deploy automatically after a successful push to `main`. Only one
polling instance should run for the Telegram bot token.
