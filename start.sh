#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "========================================"
echo "  Algorithm Validation Platform"
echo "========================================"
echo

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[ERROR] Python not found. Please install Python 3.8+ first."
  exit 1
fi

echo "[OK] Python detected:"
"$PYTHON_BIN" --version
echo

if [[ ! -d ".venv" ]]; then
  echo "[INFO] Creating virtual environment: .venv"
  "$PYTHON_BIN" -m venv .venv
fi

if [[ -f ".venv/bin/activate" ]]; then
  # macOS/Linux
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [[ -f ".venv/Scripts/activate" ]]; then
  # Git Bash/MSYS fallback on Windows
  # shellcheck disable=SC1091
  source ".venv/Scripts/activate"
fi

echo "[INFO] Installing required packages..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo

# Helps PyQt5 render correctly on some macOS/Qt combinations.
export QT_MAC_WANTS_LAYER=1

echo "[INFO] Starting Algorithm Validation Platform..."
python algorithm_platform.py
