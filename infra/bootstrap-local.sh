#!/usr/bin/env bash
# Creates the role + database that DATABASE_URL points at, using host postgres.
# The docker compose path does this via POSTGRES_USER/POSTGRES_DB instead.
# Safe to re-run: every step is a no-op if it already exists.
set -euo pipefail

DB_USER=${DB_USER:-setu}
DB_PASS=${DB_PASS:-setu}
DB_NAME=${DB_NAME:-swasthya}

command -v psql >/dev/null || { echo "psql not found — install postgres 16+ first"; exit 1; }
pg_isready -q || { echo "postgres is not accepting connections"; exit 1; }

psql -d postgres -tAc "select 1 from pg_roles where rolname='$DB_USER'" | grep -q 1 || \
  psql -d postgres -q -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS' CREATEDB;"

psql -d postgres -tAc "select 1 from pg_database where datname='$DB_NAME'" | grep -q 1 || \
  psql -d postgres -q -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

# gen_random_uuid() is core from postgres 13 on; fail loudly rather than at migrate time
psql -U "$DB_USER" -h localhost -d "$DB_NAME" -tAc "select gen_random_uuid()" >/dev/null

redis-cli ping >/dev/null 2>&1 || echo "warning: redis is not responding on localhost:6379"

echo "ready: $DB_USER@$DB_NAME"
