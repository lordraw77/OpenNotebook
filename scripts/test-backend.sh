#!/usr/bin/env bash
# Run the backend test suite against disposable PostgreSQL and Redis containers.
# Requires Docker and uv. Containers are removed on exit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUFFIX="$$"
PG="on-test-pg-$SUFFIX"
RD="on-test-redis-$SUFFIX"

cleanup() { docker rm -f "$PG" "$RD" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$PG" -e POSTGRES_USER=opennotebook -e POSTGRES_PASSWORD=test -e POSTGRES_DB=opennotebook \
  -p 127.0.0.1::5432 postgres:18.6-alpine >/dev/null
docker run -d --name "$RD" -p 127.0.0.1::6379 redis:8.8.4-alpine >/dev/null

PG_PORT="$(docker port "$PG" 5432/tcp | head -1 | awk -F: '{print $NF}')"
RD_PORT="$(docker port "$RD" 6379/tcp | head -1 | awk -F: '{print $NF}')"

for _ in $(seq 1 60); do
  docker exec "$PG" pg_isready -U opennotebook >/dev/null 2>&1 && break
  sleep 1
done

cd "$ROOT/backend"
TEST_DATABASE_URL="postgresql+psycopg://opennotebook:test@127.0.0.1:${PG_PORT}/opennotebook_test" \
TEST_REDIS_URL="redis://127.0.0.1:${RD_PORT}/15" \
  uv run pytest "$@"
