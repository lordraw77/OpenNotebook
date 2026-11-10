#!/usr/bin/env bash
# Regenerates the user-guide screenshots (frontend/public/guide/{en,it}/*.webp) with the real UI and a demo backend.
# Needs: the test PostgreSQL/Redis containers (see backend/tests/conftest.py), backend/.venv, frontend/node_modules and
# Playwright with a Chromium (NODE_PATH is taken from `npm root -g`). Nothing is sent to any provider.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="$(mktemp -d)"
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$tmp"' EXIT
(cd "$root/frontend" && npx ng serve --proxy-config proxy.conf.json --port 4200 >"$tmp/ng.log" 2>&1) &
until curl -s -o /dev/null localhost:4200/; do sleep 2; done
for lang in ${LANGS:-en it}; do
  (cd "$root/backend" && DEMO_LANG=$lang exec .venv/bin/python ../scripts/docs/demo_server.py >"$tmp/demo-$lang.log" 2>&1) &
  server=$!
  until grep -q "demo ready" "$tmp/demo-$lang.log"; do sleep 2; kill -0 $server || { cat "$tmp/demo-$lang.log"; exit 1; }; done
  NODE_PATH="$(npm root -g)" node "$root/scripts/docs/capture.cjs" "$lang" "$tmp/shots-$lang"
  kill $server 2>/dev/null || true; wait $server 2>/dev/null || true
  mkdir -p "$root/frontend/public/guide/$lang"
  "$root/backend/.venv/bin/python" - "$tmp/shots-$lang" "$root/frontend/public/guide/$lang" <<'PY'
import sys
from pathlib import Path
from PIL import Image
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
for png in sorted(src.glob("*.png")):
    Image.open(png).convert("RGB").save(dst / f"{png.stem}.webp", "WEBP", quality=82, method=6)
PY
done
