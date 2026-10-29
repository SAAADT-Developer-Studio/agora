#!/usr/bin/env bash
# Per-boot reconciliation for the Vidik (agora) development environment.
# Brings up local Postgres, ensures the dev role/database and schema exist, and
# seeds the news providers so the API has data to serve. Safe to run repeatedly.
set -uo pipefail

export PATH="$HOME/.local/bin:$PATH"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PG_VER="$(ls /usr/lib/postgresql/ 2>/dev/null | sort -n | tail -1)"
PG_VER="${PG_VER:-16}"

# Start the Postgres cluster if it is not already online (no systemd in the VM).
if ! sudo pg_lsclusters -h 2>/dev/null | awk '{print $4}' | grep -q online; then
  sudo pg_ctlcluster "$PG_VER" main start || true
fi

# Wait for Postgres to accept connections.
for _ in $(seq 1 30); do
  if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Ensure the dev role and database exist (idempotent).
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='vidik'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE vidik LOGIN PASSWORD 'vidik';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='vidik'" | grep -q 1 \
  || sudo -u postgres createdb -O vidik vidik
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE vidik TO vidik;" >/dev/null 2>&1

# Bootstrap the schema from the current ORM models and mark Alembic at head.
# The initial Alembic migration is an empty stub (the baseline tables predate
# Alembic), so a fresh database is built from the models and then stamped.
cd "$REPO_ROOT/scraper"
uv run python -c "from app.database.schema import Base, engine; Base.metadata.create_all(engine)"
uv run alembic stamp head >/dev/null 2>&1 || true

# Seed the news providers (idempotent upsert) so the API returns data.
uv run python -c "
from app.database.services import NewsProviderService
from app.providers.providers import PROVIDERS
NewsProviderService.sync_providers(PROVIDERS)
print(f'start.sh: seeded {len(PROVIDERS)} news providers')
"

echo "start.sh: complete (postgres online, schema ready, providers seeded)"
