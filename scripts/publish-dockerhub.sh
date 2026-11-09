#!/usr/bin/env bash
# Build the OpenNotebook images (web, api, worker, converter), verify they contain no models, push <version> and `latest` to Docker Hub,
# then create/update the repositories and their overview (docs/dockerhub/).
#   scripts/publish-dockerhub.sh <version> [namespace]
# Requires `docker login` (or DOCKERHUB_USERNAME / DOCKERHUB_TOKEN for the overview update).
set -euo pipefail

VERSION="${1:?version, e.g. 0.4.0}"
NS="${2:-lordraw}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$VERSION" != "dev" ]] || { echo "Use a release version, not dev"; exit 1; }

echo "== build $NS/opennotebook-{web,api,worker,converter}:$VERSION"
docker build --build-arg VERSION="$VERSION" -t "$NS/opennotebook-web:$VERSION" "$ROOT/frontend"
docker build --build-arg VERSION="$VERSION" --target api -t "$NS/opennotebook-api:$VERSION" "$ROOT/backend"
docker build --build-arg VERSION="$VERSION" --target worker -t "$NS/opennotebook-worker:$VERSION" "$ROOT/backend"
docker build --build-arg VERSION="$VERSION" -t "$NS/opennotebook-converter:$VERSION" "$ROOT/converter"

echo "== check: no models inside"
"$ROOT/scripts/check-no-models.sh" "$NS/opennotebook-api:$VERSION" "$NS/opennotebook-worker:$VERSION" \
  "$NS/opennotebook-converter:$VERSION"

echo "== create/update repositories and overviews"
python3 "$ROOT/scripts/dockerhub_repos.py" "$NS" "$VERSION"

echo "== push"
for img in web api worker converter; do
  docker tag "$NS/opennotebook-$img:$VERSION" "$NS/opennotebook-$img:latest"
  docker push "$NS/opennotebook-$img:$VERSION"
  docker push "$NS/opennotebook-$img:latest"
done
echo "published $NS/opennotebook-{web,api,worker,converter}:$VERSION (+ latest)"
