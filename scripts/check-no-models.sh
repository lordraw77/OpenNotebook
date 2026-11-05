#!/usr/bin/env bash
# Fail if an image contains ML runtimes or model weight files (ADR-008: no models inside the stack).
# Usage: scripts/check-no-models.sh image[:tag] [image[:tag] ...]
set -euo pipefail

status=0
for image in "$@"; do
  echo "checking $image"
  if ! docker run --rm --entrypoint sh "$image" -c '
    set -e
    found=0
    for pkg in torch tensorflow jax onnxruntime transformers sentence_transformers vllm llama_cpp ctranslate2 paddle paddleocr docling; do
      if python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(\"$pkg\") else 1)" 2>/dev/null; then
        echo "  forbidden Python package: $pkg"; found=1
      fi
    done
    weights=$(find / -xdev -type f \( -name "*.safetensors" -o -name "*.gguf" -o -name "*.onnx" -o -name "*.pt" -o -name "*.ckpt" -o \( -name "*.pth" -size +1M \) \) 2>/dev/null | head -20)
    if [ -n "$weights" ]; then echo "  model weight files:"; echo "$weights" | sed "s/^/    /"; found=1; fi
    exit $found
  '; then
    status=1
  else
    echo "  ok: no ML runtimes or model weights"
  fi
done
exit $status
