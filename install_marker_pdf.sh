#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/kalinicenkovitalijmikolajovic/.codex/worktrees/5c15/Script_for_translate_book"
VENV_DIR="$ROOT_DIR/.venv_marker"
PYTHON_BIN="$VENV_DIR/bin/python"
MARKER_VERSION="1.10.2"

cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed." >&2
  exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
  uv venv --python 3.14 "$VENV_DIR"
fi

uv pip install --python "$PYTHON_BIN" \
  "marker-pdf==${MARKER_VERSION}" \
  "pypdf" \
  "python-dotenv" \
  "requests" \
  "tqdm"
