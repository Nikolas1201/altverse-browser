#!/usr/bin/env bash
# AltVerse one-shot setup for Linux.
set -e
cd "$(dirname "$0")"

echo "[AltVerse] Installing Python packages..."
python3 -m pip install --quiet --disable-pip-version-check flask requests pywebview waitress

if ! command -v lemonade >/dev/null 2>&1; then
  echo "[AltVerse] Lemonade Server not found."
  echo "  Install it first: https://lemonade-server.ai/docs/guide/install/"
  echo "  (Ubuntu example: sudo add-apt-repository ppa:lemonade-sdk/lemonade"
  echo "                   sudo apt update && sudo apt install lemonade-server)"
  exit 1
fi

if command -v nvidia-smi >/dev/null 2>&1; then BACKEND=cuda; else BACKEND=vulkan; fi
echo "[AltVerse] GPU backend: $BACKEND"

MODEL=$(head -n1 model.txt 2>/dev/null || echo "Qwen3-4B-Instruct-2507-GGUF")
echo "[AltVerse] Installing backend and model: $MODEL"
lemonade backends install "llamacpp:$BACKEND" || true
lemonade pull "$MODEL"

echo "[AltVerse] Setup complete. Launch with ./run-linux.sh"