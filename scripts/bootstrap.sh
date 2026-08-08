#!/usr/bin/env bash
set -euo pipefail

echo "[bootstrap] Creating Python virtual environment in .venv"
python -m venv .venv

# Activate venv for the rest of the script (POSIX shells)
# Note: running this script will activate the venv only for the script's shell.
# Users should `source .venv/bin/activate` to enter the environment interactively.
. .venv/bin/activate

echo "[bootstrap] Upgrading pip and installing requirements"
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
else
    echo "[bootstrap] WARNING: requirements.txt not found. Install dependencies manually."
fi

# Install Playwright browsers (useful for E2E tests)
if python -m playwright --version > /dev/null 2>&1; then
    echo "[bootstrap] Installing Playwright browsers"
    python -m playwright install --with-deps || true
else
    echo "[bootstrap] Playwright not installed; skipping browser install"
fi

echo "[bootstrap] Done. Activate the venv with: source .venv/bin/activate"