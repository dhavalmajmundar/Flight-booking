# Flight Bot Handoff

Last updated: 2026-09-07

## Current status

- Repository: `dhavalmajmundar/Flight-booking`
- Production branch: `main`
- Intended hosting: Oracle VM via Coolify, using
  `/home/ubuntu/flight-booking-app` and `docker-compose.oracle.yml`. GitHub
  deployment metadata still shows an attached Railway production service;
  confirm one host and disable the other to prevent duplicate Telegram polling.
- Runtime: Python Telegram bot using long polling
- Flight provider: RouteStack
- Handoff policy: update this file in every completed change; use `git log -1`
  for the commit containing the latest handoff
- Verification: 66 Python tests passing; Python compile clean.
  Flutter widget tests and Android/Windows release jobs unchanged since the
  last verified run (`30063237947` for source commit `47e7fc3`); this change
  touches `flight_bot/routestack.py` and `tests/test_routestack.py`.

## 2026-09-07 outage and ship review

- Telegram `getMe` succeeds, webhook is correctly empty, but a direct polling
  probe returned an unclaimed `getUpdates` response: no bot process was polling.
  Bot token/API registration is healthy; deployment process needs restart.
- Local Oracle SSH probe reached `150.136.102.196` but available machine keys
  were not authorized, so container status/restart could not be performed here.
- Fixed `avoided_airlines`: matching fares remain visible, receive a prominent
  warning, and get a strong ranking penalty. Previously this saved option had no
  ranking effect.
- Fixed max-budget behavior: RouteStack result assembly no longer silently
  drops over-budget fares. Ranking keeps them visible and adds the promised
  over-budget warning/penalty.
- Added regression tests for both defects. No client rebuild required; changes
  affect server-side search/ranking only.
- Local same-env startup exposed a Python 3.14 incompatibility in
  `python-telegram-bot` polling internals. Production Docker uses Python 3.12;
  package metadata now explicitly supports Python `>=3.11,<3.14` so unsupported
  local runtimes fail clearly during installation instead of at bot startup.
- GitHub/Railway deployment of commit `8485760` reported success, but the bot
  token still had no active poller afterward. Coolify is reachable at the Oracle
  host but requires user login; inspect/restart the `flight-booking` service
  there next. Railway dashboard also requires login. Do not enable both hosts.
- User signed into Coolify. Flight Booking was not a managed Coolify project;
  it appeared under Server → Resources → Unmanaged as the manually composed
  `flight-booking` container. Coolify showed it as running even though Telegram
  had no active poller. Restarting only that container restored polling; a
  follow-up `getUpdates` probe returned the expected `409 Conflict`, confirming
  an active long-poll request. `flight-postgres` was not restarted.
- Coolify's browser terminal cannot connect because its real-time service/port
  is unavailable. Oracle SSH also needs the user's authorized private key.
  Therefore the container was restarted but its on-host checkout/image was not
  pulled or rebuilt from commits `8485760` / `017d2b2`; deploy those changes on
  Oracle before calling the reviewed server code shipped.

## Flight search timeout extension and clean exception handling

- Resolved an issue where flexible flight searches (which trigger multiple concurrent requests to RouteStack) failed with a blank error message (`I couldn't complete the live search: `) due to slow RouteStack API responses.
- Increased the HTTPX client timeout from `35.0` to `60.0` seconds to give slow flight searches more time to compile results.
- Enhanced exception mapping in `RouteStackClient.search`: standard network timeouts/failures are now captured and mapped to clear error messages (e.g., "RouteStack search request timed out.") instead of propagating empty exception strings.
- Added test coverage via `test_search_timeout_handling` in `tests/test_routestack.py`.

## Failed watch checks refund usage and retry without over-escalating

- A failed watch check previously consumed its daily-cap token permanently
  and left the watch's `next_check_at` at the full adaptive interval set by
  `claim()` before the search ran, so a single transient failure could
  silently cost a token and delay the next real attempt by up to 48 hours.
- `WatchStore.decrement_usage()` refunds the exact number of tokens claimed
  for a check that produced no price observation (1 normally, 7 for a
  weekly-flex scan, confirmed by test).
- The refund path distinguishes two cases in `_check_watch`:
  - Zero ranked results (no offers on the route/date, or a
    `required_airlines` filter nothing currently satisfies) is not a
    provider error. The token is refunded but the watch stays on its normal
    adaptive cadence — `consecutive_failures` and backoff are not touched.
    A watch with a permanently unsatisfiable filter would otherwise get
    escalated toward `/cleanup` and retried hourly forever for no reason.
  - An actual `FlightSearchError` or unexpected exception refunds the token
    and reschedules via `defer_watch()` to
    `min(2 ** watch.consecutive_failures, interval)` hours: 1h after the
    first failure, backing off exponentially. Once `consecutive_failures`
    reaches 3, it stops backing off within that tight window and falls back
    to the watch's full adaptive interval instead, so a longer RouteStack
    outage doesn't turn into hourly retries against the provider all day.
- `consecutive_failures` bookkeeping and the existing `/cleanup` suggestion at
  3+ consecutive failures are unchanged.
- Known limitation: refunding the internal daily-cap counter does not reduce
  actual RouteStack calls made during retries. If RouteStack bills per
  attempt regardless of success, a bad outage still generates real billed
  calls up to the fast-retry cap before falling back to the slow interval.

## Current user checkpoint

- Oracle VM/Coolify deployment is configured and confirmed running.
- The Railway PostgreSQL service was stopped after `DATABASE_PUBLIC_URL` was
  switched to the VM-hosted PostgreSQL/Supabase endpoint and the Telegram bot
  replied successfully to a guided search.
- The original Windows app was extracted to the ignored local
  `/Flight-Companion/` folder and successfully connected to Railway.
- Refreshed compact-layout packages are ready under `client_app/releases/`.
- Next guided step: close the running Windows app, replace the contents of the
  extracted `/Flight-Companion/` folder with the refreshed Windows ZIP contents,
  then launch `FlightCompanion.exe` and visually confirm Search and Settings.
- Continue installation guidance one step at a time, as requested by the user.

## Airport and airline helpers

- Search and Watch route fields use the bundled `airportsdata` IATA database
  through the owner-authenticated Railway API. Typing an exact code such as
  `CLT` displays `[CLT] Charlotte Douglas International Airport, Charlotte,
  North Carolina, US`; city/state text shows selectable nearby suggestions.
- Airport lookups are debounced and cached in the app. They use no RouteStack
  search token and repeated queries do not make another Railway request during
  that app session.
- Search exposes three different airline controls:
  - Only these airlines: a strict result filter; multiple codes match any listed
    airline present in an itinerary.
  - Preferred airlines: ranking boost without hiding other results.
  - Airlines to avoid: the existing avoidance preference.
- The strict airline filter persists in PostgreSQL profile defaults, applies to
  live searches and saved watches, survives watch JSON serialization, and is
  included in private data export.
- PostgreSQL startup migration adds `user_profiles.required_airlines` safely
  with an empty-array default for existing Railway databases.

## Compact desktop UI

- Search keeps route/date controls visible and organizes the remaining options
  into three fixed-height desktop tabs: Trip preferences, Comfort & price, and
  Search strategy. The live-search button fits without page scrolling at the
  application's normal `1179 x 993` content viewport.
- Settings uses balanced two-column cards on desktop and also fits that viewport
  without page scrolling.
- Narrow/mobile screens retain the touch-friendly single-column scrolling form.
- Regression tests verify Search and Settings fit, every Search tab opens, the
  expected option groups remain available, and no RenderFlex overflow occurs.
- Refreshed local packages:
  - Android `FlightCompanion-Android.apk` SHA-256
    `32391B8FE94B970CCF8712B84338E1B869B53024FDBFF1D569C240C5114DDF7A`
  - Windows `FlightCompanion-Windows.zip` SHA-256
    `10D9721185DF4DC654BAFDE9253C71D592914544FE712D28320F6AD1B9748895`
- The user's extracted `/Flight-Companion/` folder and root Windows ZIP are
  ignored by Git and must not be committed.

## Companion applications

- `client_app/` is one responsive Flutter codebase for Android and Windows.
- Search exposes every supported route, date, traveler, cabin, currency,
  flexibility, nearby-airport, baggage, budget, airline, priority, time, stop,
  red-eye, connection, duration, and search-strategy control.
- Watches create and manage target/drop/interval/lifetime/weekly-flex monitors
  and render Postgres price history as a native line chart.
- Dashboard includes health, usage forecasts, stored deals, cleanup, and private
  JSON backup. Settings includes every saved profile and quiet-hour default.
- `flight_bot/api.py` provides the owner-only FastAPI surface. Every `/api/v1`
  route requires `Authorization: Bearer APP_ACCESS_TOKEN`; the public root only
  reports service status. Secrets never appear in responses.
- `flight_bot/main.py` runs the API on Railway's `PORT` beside Telegram long
  polling, with independent database and RouteStack clients for each event loop.
- `.github/workflows/build-apps.yml` tests and builds Android and Windows on
  `main` or manual dispatch. Windows is zipped with its required DLLs/data.
- Generated binaries live under `client_app/releases/` locally and are ignored
  by Git; the source, lockfile, platform runners, and reproducible CI stay in Git.
- Verified personal-install packages: `FlightCompanion-Android.apk` and the full
  Windows runtime bundle `FlightCompanion-Windows.zip`.
- Railway needs `APP_ACCESS_TOKEN` and a public HTTPS domain before app login.

## User experience

- `/search` starts the guided search.
- Guided search uses an inline month calendar for the start date and reply
  buttons for trip type, round-trip duration, 1–9 passengers, cabin, flexibility,
  ±1/2/3/5/7 flexible days, nearby-airport behavior, separate checked/carry-on
  baggage, currency, departure window, maximum stops, red-eye policy, connection
  comfort, maximum duration, budget presets, skip choices, and ranking. Each
  screen marks the current safe or saved default.
- `/flight ORIGIN DESTINATION YYYY-MM-DD` starts a one-line search.
- `/quick New York to Paris on October 10, 2026 for 8 days` uses a bounded local
  parser, saved defaults, and the normal confirmation; it consumes no AI tokens.
- Multi-word cities, states, and airport names use pipe separators, for example
  `/flight New York, NY | Los Angeles, CA | 2026-09-15`. The same format works
  for `/watch`.
- `/defaults` explains the smart defaults without using RouteStack.
- `/watch` with no arguments launches a button-driven wizard for route, date,
  trip type/duration, target, drop threshold, interval, lifetime, and weekly
  flexible scan. Defaults are visibly selected and no fare token is used during
  setup. One-line `/watch` remains available.
- `/watches`, `/history`, `/checknow`, `/unwatch`, `/usage`, `/deals`, `/chart`,
  `/booked`, `/cleanup`, `/health`, and `/export` manage watches and operations.
- The bot registers all 24 owner commands with Telegram during startup so typing
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
- The full comparison shows a green/yellow/red date-price calendar, cheapest live
  departure day, and savings versus the requested date.
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
- `/profile` persists airline, budget, travelers, cabin, baggage, currency,
  departure window, red-eye, stop, layover, and duration defaults for guided and
  one-line searches.
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
  values are deliberately wider planning bands. Buttons and custom amounts use
  the selected currency. No RouteStack call is used to create budget choices.
- Result cards add per-traveler prices, difference from cheapest, and cost per
  hour saved for a faster, more expensive option.
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
- Duplicate route/date/traveler/cabin watches are detected before creation and
  can update the existing watch's target, schedule, expiry, and weekly scan.
- Watches default to one exact route/date search and a 24-hour base interval.
- Scheduling conserves calls far from departure, becomes more frequent near
  departure or a target price, and prioritizes urgent due watches within the
  unchanged global daily cap.
- Flexible dates and nearby airports are disabled for normal recurring checks.
  `--weekly-flex yes` opts into a weekly ±3 scan only when seven calls remain
  under the daily cap; it replaces that cycle's exact-date check.
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
- Stored itinerary metadata detects airline, departure-time, checked-bag, stop,
  and duration changes in addition to price changes.
- Weekly scans offer Switch date, Watch both, or Keep current date when another
  date is at least 5% cheaper. Alerts also identify recovery near an observed low
  after a 10%+ rise.
- Profile timezone and quiet hours default to `America/New_York`, 22:00–07:00.
  Nonurgent checks are deferred before consuming a call; departures within three
  days or prices within 5% of target remain urgent.
- `/deals`, `/chart`, and the enhanced `/usage` operate entirely on stored data.
  `/health` performs no fare search. `/export` provides owner-only JSON without
  credentials. `/cleanup` suggests stale watches; nothing is removed without an
  explicit `/unwatch` or `/booked` action.

## Provider limitations

- RouteStack's public schema does not currently document dependable inputs for
  children/infants, multi-city itineraries, seat maps, or complete fare rules.
  The bot deliberately avoids nonfunctional controls for them.
- Verify exact baggage, change/cancellation rules, and seats during the
  revalidated checkout handoff.

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
