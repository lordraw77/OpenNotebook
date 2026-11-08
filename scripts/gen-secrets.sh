#!/usr/bin/env bash
# Create the env file from .env.example if it does not exist, then fill every EMPTY internal secret.
# Existing values (including provider keys) are never changed. Safe to run repeatedly.
set -euo pipefail

ENV_FILE="${1:-.env}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Template: the repository's .env.example, or one next to this script / in the current directory
# (deployments that downloaded only deploy/production/ files).
TEMPLATE="$ROOT/.env.example"
for candidate in "$TEMPLATE" "$(dirname "$0")/.env.example" ./.env.example; do
  [[ -f "$candidate" ]] && TEMPLATE="$candidate" && break
done

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$TEMPLATE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "created $ENV_FILE from .env.example"
fi

rand() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-"$1"; }

# name -> generator
declare -A GEN=(
  [APP_SECRET_KEY]="rand 64"
  [APP_ENCRYPTION_KEY]="openssl rand -base64 32"
  [POSTGRES_PASSWORD]="rand 32"
  [QDRANT_API_KEY]="rand 40"
  [REDIS_PASSWORD]="rand 32"
  [S3_ACCESS_KEY]="rand 20"
  [S3_SECRET_KEY]="rand 40"
  [BOOTSTRAP_ADMIN_PASSWORD]="rand 20"
  [KEYCLOAK_ADMIN_PASSWORD]="rand 24"
  [GRAFANA_ADMIN_PASSWORD]="rand 24"
)

current() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//; s/^[[:space:]]+|[[:space:]]+$//g'; }

for name in "${!GEN[@]}"; do
  value="$(current "$name" || true)"
  [[ -n "$value" ]] && continue
  new="$(eval "${GEN[$name]}")"
  if grep -qE "^$name=" "$ENV_FILE"; then
    # replace the empty assignment, keeping any trailing comment out of the value
    tmp="$(mktemp)"
    awk -v k="$name" -v v="$new" 'BEGIN{FS=OFS="="} $1==k && !done {print k "=" v; done=1; next} {print}' "$ENV_FILE" >"$tmp"
    cat "$tmp" >"$ENV_FILE" && rm -f "$tmp"
  else
    printf '%s=%s\n' "$name" "$new" >>"$ENV_FILE"
  fi
  echo "generated $name"
  [[ "$name" == "BOOTSTRAP_ADMIN_PASSWORD" ]] && admin_pw="$new"
done

if [[ -z "$(current BOOTSTRAP_ADMIN_EMAIL || true)" ]]; then
  if grep -qE '^BOOTSTRAP_ADMIN_EMAIL=' "$ENV_FILE"; then
    sed -i -E 's/^BOOTSTRAP_ADMIN_EMAIL=.*/BOOTSTRAP_ADMIN_EMAIL=admin@example.com/' "$ENV_FILE"
  else
    echo "BOOTSTRAP_ADMIN_EMAIL=admin@example.com" >>"$ENV_FILE"
  fi
  echo "set BOOTSTRAP_ADMIN_EMAIL=admin@example.com (change it before the first start if you want)"
fi

if [[ -n "${admin_pw:-}" ]]; then
  echo "first admin password: $admin_pw   (stored in $ENV_FILE as BOOTSTRAP_ADMIN_PASSWORD; used only at first start)"
fi
