#!/usr/bin/env bash
# Restore an OpenNotebook backup made by scripts/backup.sh into the stack found by `docker compose`
# (or COMPOSE=...). Everything currently stored is REPLACED.
#
#   scripts/restore.sh BACKUP_DIR [--yes]
#
# The .env of the target must hold the same APP_ENCRYPTION_KEY as the backup (provider keys are encrypted
# with it); the backup's copy is in BACKUP_DIR/env. Database migrations run afterwards (`up` starts the
# migrate job), so a backup of an older version is upgraded.
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"
DIR="${1:?backup directory}"
YES="${2:-}"
[[ -f "$DIR/database.dump" && -f "$DIR/blobs.tgz" ]] || { echo "$DIR is not an OpenNotebook backup" >&2; exit 1; }
(cd "$DIR" && python3 - <<'PY'
import hashlib, json
m = json.load(open("manifest.json"))
for name, digest in m["files"].items():
    if hashlib.sha256(open(name, "rb").read()).hexdigest() != digest:
        raise SystemExit(f"checksum mismatch: {name}")
print(f"backup of {m['created_at']}, version {m['version']}, {m['sources']} sources: checksums ok")
PY
)
if [[ "$YES" != "--yes" ]]; then
  read -r -p "Replace ALL data of this installation with the backup? Type 'restore': " answer
  [[ "$answer" == "restore" ]] || { echo "aborted"; exit 1; }
fi

volume_of() {
  docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" "$($COMPOSE ps -aq "$1")"
}

echo "- starting storage services, stopping the application"
$COMPOSE up -d --wait postgres seaweedfs qdrant redis >/dev/null
$COMPOSE stop web api worker >/dev/null 2>&1 || true
blob_volume="$(volume_of seaweedfs /data)"
qdrant_volume="$(volume_of qdrant /qdrant/storage)"

echo "- database"
$COMPOSE exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
$COMPOSE exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' <"$DIR/database.dump"

restore_volume() {  # service, volume, archive
  $COMPOSE stop "$1" >/dev/null
  docker run --rm -v "$2:/data" -v "$(cd "$DIR" && pwd):/backup:ro" alpine:3.22 \
    sh -c "find /data -mindepth 1 -delete && tar xzf /backup/$3 -C /data"
  $COMPOSE start "$1" >/dev/null
}
echo "- original files"
restore_volume seaweedfs "$blob_volume" blobs.tgz
if [[ -f "$DIR/qdrant.tgz" ]]; then
  echo "- vector index"
  restore_volume qdrant "$qdrant_volume" qdrant.tgz
else
  echo "- no vector index in the backup: re-index the projects from RAG Status after the restore"
fi

echo "- starting the application (migrations run first)"
$COMPOSE up -d >/dev/null
echo "restored from $DIR"
