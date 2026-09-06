#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${HF_HOME:-/data/hf}"

# Railway injeta PORT. server.py adiciona a UI, /usar e a API key opcional.
exec python server.py
