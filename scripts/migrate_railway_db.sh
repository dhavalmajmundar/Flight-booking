#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

tr -d '\r' < .env.oracle > .env.oracle.lf

set -a
. ./.env.oracle.lf
set +a

if [ -z "${DATABASE_PUBLIC_URL:-}" ]; then
  echo "DATABASE_PUBLIC_URL is missing" >&2
  exit 1
fi

mkdir -p backups

docker run --rm \
  -e DATABASE_PUBLIC_URL="$DATABASE_PUBLIC_URL" \
  -v "$PWD/backups:/backup" \
  postgres:18-alpine \
  pg_dump "$DATABASE_PUBLIC_URL" --format=custom --no-owner --no-privileges --file=/backup/railway-flight.dump

docker run --rm \
  --network flight-booking-app_default \
  -e DATABASE_URL="$DATABASE_URL" \
  -v "$PWD/backups:/backup" \
  postgres:18-alpine \
  pg_restore --clean --if-exists --no-owner --no-privileges \
  --dbname="$DATABASE_URL" /backup/railway-flight.dump
