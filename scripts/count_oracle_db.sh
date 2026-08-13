#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

tr -d '\r' < .env.oracle > .env.oracle.lf

set -a
. ./.env.oracle.lf
set +a

for table in flight_watches watch_prices watch_usage watch_notifications user_profiles recent_searches; do
  printf '%s=' "$table"
  docker run --rm \
    --network flight-booking-app_default \
    -e DATABASE_URL="$DATABASE_URL" \
    postgres:18-alpine \
    psql "$DATABASE_URL" -Atc "SELECT COUNT(*) FROM $table"
done
