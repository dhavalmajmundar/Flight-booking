# Local installable builds

Release binaries are placed here after a successful build:

- `FlightCompanion-Android.apk`
- `FlightCompanion-Windows.zip`

The binaries are intentionally ignored by Git because they are large generated
files. The complete Flutter source, platform runners, lockfile, and GitHub Actions
workflow are versioned, so either package can be recreated at any time. GitHub
Actions also retains downloadable build artifacts for each successful workflow.
