#!/usr/bin/env bash
# Build a release tarball for hosts without registry access:
#   opennotebook-<version>-bundle.tar.gz = docker-saved images + compose + .env.example + install.sh
# Model providers must still be reachable from the target host.
set -euo pipefail

VERSION="${1:?version}"
REGISTRY="${2:-opennotebook}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/opennotebook-$VERSION"

rm -rf "$OUT" && mkdir -p "$OUT/deploy/compose"
cp -r "$ROOT/deploy/compose/." "$OUT/deploy/compose/"
cp "$ROOT/.env.example" "$OUT/.env.example"
mkdir -p "$OUT/scripts" && cp "$ROOT/scripts/gen-secrets.sh" "$OUT/scripts/"

images=(
  "$REGISTRY/web:$VERSION" "$REGISTRY/api:$VERSION" "$REGISTRY/worker:$VERSION"
  postgres:18.6-alpine qdrant/qdrant:v1.20.0 chrislusf/seaweedfs:4.52 redis:8.8.4-alpine
)
for img in "${images[@]}"; do docker image inspect "$img" >/dev/null 2>&1 || docker pull "$img"; done
echo "saving ${#images[@]} images"
docker save "${images[@]}" | gzip -1 >"$OUT/images.tar.gz"

cat >"$OUT/install.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\$0")"
docker load -i images.tar.gz
[ -f .env ] || scripts/gen-secrets.sh .env
echo "Edit .env to add provider keys, then press Enter to start."; read -r _
VERSION=$VERSION REGISTRY=$REGISTRY docker compose --env-file .env -f deploy/compose/docker-compose.yml up -d --no-build
EOF
chmod +x "$OUT/install.sh"

tar -C "$ROOT/dist" -czf "$ROOT/dist/opennotebook-$VERSION-bundle.tar.gz" "opennotebook-$VERSION"
echo "created dist/opennotebook-$VERSION-bundle.tar.gz"
