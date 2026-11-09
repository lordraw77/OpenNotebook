#!/usr/bin/env bash
# Back up an OpenNotebook installation: database, original files (SeaweedFS), vector index (Qdrant), .env.
#
#   scripts/backup.sh [-o DIR] [--env-file PATH] [--no-vectors] [--no-env]
#
# Run it where `docker compose` finds the stack: the deployment directory (docker-compose.yml + .env), or set
# COMPOSE, e.g. COMPOSE="docker compose --env-file .env -f deploy/compose/docker-compose.yml" (make backup).
# Storage and vector containers are paused for the few seconds their volumes are copied (consistent copy);
# the database is dumped online.
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"
OUT_ROOT="./backups"
VECTORS=1
ENVFILE=1
# The env file of the stack: explicit, or the one the Makefile uses, or ./.env of the deployment directory.
ENV_SRC="${OPENNOTEBOOK_ENV_FILE:-.env}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) OUT_ROOT="$2"; shift 2 ;;
    --no-vectors) VECTORS=0; shift ;;
    --no-env) ENVFILE=0; shift ;;
    --env-file) ENV_SRC="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_ROOT/opennotebook-$stamp"
mkdir -p "$OUT"
chmod 700 "$OUT"
echo "backup -> $OUT"

volume_of() {  # named volume mounted by a service at a path
  local cid
  cid="$($COMPOSE ps -q "$1")"
  [[ -n "$cid" ]] || { echo "service $1 is not running" >&2; exit 1; }
  docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" "$cid"
}

copy_volume() {  # service, mount path, archive name
  local volume
  volume="$(volume_of "$1" "$2")"
  $COMPOSE pause "$1" >/dev/null
  trap '$COMPOSE unpause '"$1"' >/dev/null 2>&1 || true' EXIT
  docker run --rm -v "$volume:/data:ro" -v "$(cd "$OUT" && pwd):/backup" alpine:3.22 \
    tar czf "/backup/$3" -C /data .
  $COMPOSE unpause "$1" >/dev/null
  trap - EXIT
}

echo "- database"
$COMPOSE exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$OUT/database.dump"
echo "- original files (SeaweedFS)"
copy_volume seaweedfs /data blobs.tgz
if [[ $VECTORS == 1 ]]; then
  echo "- vector index (Qdrant)"
  copy_volume qdrant /qdrant/storage qdrant.tgz
fi
if [[ $ENVFILE == 1 ]]; then
  if [[ -f "$ENV_SRC" ]]; then
    cp "$ENV_SRC" "$OUT/env"
    chmod 600 "$OUT/env"
    echo "- env file $ENV_SRC (contains secrets)"
  else
    echo "- env file $ENV_SRC not found: not included (keep APP_ENCRYPTION_KEY safe separately)"
  fi
fi

version="$($COMPOSE exec -T api python -c 'import opennotebook; print(opennotebook.__version__)' 2>/dev/null | tr -d '\r' || echo unknown)"
sources="$($COMPOSE exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from sources where deleted_at is null"' | tr -d '\r')"
(
  cd "$OUT"
  printf '{\n  "created_at": "%s",\n  "version": "%s",\n  "sources": %s,\n  "files": {\n' "$stamp" "$version" "${sources:-0}"
  first=1
  for f in *; do
    [[ $f == manifest.json ]] && continue
    [[ $first == 1 ]] || printf ',\n'
    first=0
    printf '    "%s": "%s"' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"
  done
  printf '\n  }\n}\n'
) >"$OUT/manifest.json"
echo "done: $(du -sh "$OUT" | cut -f1), $sources sources, version $version"
