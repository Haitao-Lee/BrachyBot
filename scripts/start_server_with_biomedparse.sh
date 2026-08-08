#!/usr/bin/env bash
set -euo pipefail

# Start BrachyBot with the optional BiomedParse v2 runtime explicitly enabled.
# Keeping these paths in one tracked launcher prevents a server restart from
# silently falling back to the unavailable-model state.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIOMEDPARSE_ROOT="${BIOMEDPARSE_ROOT:-$HOME/snap/brachyplan/BiomedParse}"
export BIOMEDPARSE_ROOT
export BIOMEDPARSE_V2_CHECKPOINT="${BIOMEDPARSE_V2_CHECKPOINT:-$ROOT_DIR/models/ctv/biomedparse_v2/biomedparse_v2.ckpt}"
export BIOMEDPARSE_V2_TEXT_ASSETS="${BIOMEDPARSE_V2_TEXT_ASSETS:-$ROOT_DIR/models/ctv/biomedparse_v2/clip-vit-base-patch32}"
export BIOMEDPARSE_V2_PYTHON="${BIOMEDPARSE_V2_PYTHON:-$BIOMEDPARSE_ROOT/.venv/bin/python}"

if [[ -n "${BRACHYBOT_PYTHON:-}" ]]; then
  PYTHON_BIN="$BRACHYBOT_PYTHON"
elif [[ -x "$HOME/.conda/envs/brachytherapy/bin/python" ]]; then
  # Use the application environment for Flask and BrachyBot dependencies.
  PYTHON_BIN="$HOME/.conda/envs/brachytherapy/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

HOST="${BRACHYBOT_HOST:-0.0.0.0}"
PORT="${BRACHYBOT_PORT:-8080}"
exec "$PYTHON_BIN" "$ROOT_DIR/web/server.py" --host "$HOST" --port "$PORT"
