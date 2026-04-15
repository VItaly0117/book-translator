#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/kalinicenkovitalijmikolajovic/.codex/worktrees/5c15/Script_for_translate_book"
VENV_DIR="$ROOT_DIR/.venv_marker"
PYTHON_BIN="$VENV_DIR/bin/python"

cd "$ROOT_DIR"

bash "$ROOT_DIR/install_marker_pdf.sh"

"$PYTHON_BIN" "$ROOT_DIR/run_middle_scan_sequential.py"
