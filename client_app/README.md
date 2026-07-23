# Flight Companion app

One Flutter codebase for the private Android and Windows companion to the Telegram
flight bot. It connects to the authenticated API hosted by the same Railway
service. RouteStack, Telegram, and Postgres credentials never enter the app.

## Screens

- **Search:** all route, date, traveler, cabin, currency, flexibility, nearby
  airport, baggage, budget, airline, optimization, departure-time, stop, red-eye,
  connection, duration, and search-strategy options.
- **Watches:** create, inspect, check, chart, mark booked, and stop watches, with
  target, drop threshold, frequency, lifetime, and weekly-flex controls.
- **Dashboard:** health, daily cap, forecasts, deal ranking, cleanup, and backup.
- **Settings:** every saved default plus secure connection settings.

## Railway setup

1. Add `APP_ACCESS_TOKEN` to the bot service with a long random value. Never reuse
   a Telegram or RouteStack credential.
2. In Railway **Settings → Networking**, generate a public HTTPS domain.
3. Redeploy. The domain root should report `Flight Companion API` as running.
4. Enter that HTTPS domain and token in the installed app.

Generate a suitable token in PowerShell:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToBase64String($bytes)
```

## Builds

```powershell
cd client_app
flutter pub get
flutter analyze
flutter test
flutter build apk --release
flutter build windows --release
```

Android output is `build/app/outputs/flutter-apk/app-release.apk`. This personal
sideload build uses the generated development key; Play Store publication requires
a private release keystore.

Windows output is the entire `build/windows/x64/runner/Release` directory. Keep
the `.exe`, DLLs, and `data` directory together. GitHub Actions packages it as
`FlightCompanion-Windows.zip`.

`.github/workflows/build-apps.yml` builds both platforms whenever app source
changes on `main`, and supports manual runs from GitHub's Actions tab.
