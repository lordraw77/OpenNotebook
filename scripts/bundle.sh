#!/usr/bin/env bash
# Build a release tarball for hosts without registry access:
#   dist/opennotebook-<version>-bundle.tar.gz = docker-saved images + deployment Compose file + .env.example
#   + secrets/backup/restore scripts + install.sh
# Model providers must still be reachable from the target host. Profile images (Keycloak, Prometheus, Grafana,
# Jaeger) are not included: add them with EXTRA_IMAGES="..." if those profiles are needed offline.
set -euo pipefail

VERSION="${1:?version}"
REGISTRY="${2:-lordraw}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/opennotebook-$VERSION"

rm -rf "$OUT" && mkdir -p "$OUT"
cp "$ROOT/deploy/production/docker-compose.yml" "$OUT/docker-compose.yml"
cp "$ROOT/.env.example" "$OUT/.env.example"
cp "$ROOT/scripts/gen-secrets.sh" "$ROOT/scripts/backup.sh" "$ROOT/scripts/restore.sh" "$OUT/"

images=(
  "$REGISTRY/opennotebook-web:$VERSION" "$REGISTRY/opennotebook-api:$VERSION" "$REGISTRY/opennotebook-worker:$VERSION"
  postgres:18.6-alpine qdrant/qdrant:v1.20.0 chrislusf/seaweedfs:4.52 redis:8.8.4-alpine alpine:3.22
)
# shellcheck disable=SC2206
images+=(${EXTRA_IMAGES:-})
for img in "${images[@]}"; do docker image inspect "$img" >/dev/null 2>&1 || docker pull "$img"; done
echo "saving ${#images[@]} images"
docker save "${images[@]}" | gzip -1 >"$OUT/images.tar.gz"

cat >"$OUT/install.sh" <<INSTALL
#!/usr/bin/env bash
# Install OpenNotebook $VERSION from this bundle, without registry access.
#   ./install.sh            create .env (secrets generated), let you edit it, start the stack
#   ./install.sh --yes      same, without the pause (edit .env first, or later and run: docker compose up -d)
set -euo pipefail
cd "\$(dirname "\$0")"
echo "loading images"
docker load -i images.tar.gz
if [[ ! -f .env ]]; then
  ./gen-secrets.sh .env
  sed -i "s/^VERSION=.*/VERSION=$VERSION/; s#^REGISTRY=.*#REGISTRY=$REGISTRY#" .env
fi
if [[ "\${1:-}" != "--yes" ]]; then
  echo "Edit .env (BOOTSTRAP_ADMIN_EMAIL, provider keys, APP_PUBLIC_URL), then press Enter to start."
  read -r _
fi
docker compose up -d --pull never --wait
docker compose ps
echo "OpenNotebook $VERSION is running; see .env for the first administrator password."
INSTALL
chmod +x "$OUT/install.sh"

tar -C "$ROOT/dist" -czf "$ROOT/dist/opennotebook-$VERSION-bundle.tar.gz" "opennotebook-$VERSION"
echo "created dist/opennotebook-$VERSION-bundle.tar.gz ($(du -h "$ROOT/dist/opennotebook-$VERSION-bundle.tar.gz" | cut -f1))"
