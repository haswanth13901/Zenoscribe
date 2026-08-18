#!/usr/bin/env bash
set -euo pipefail

echo "[bootstrap] Creating Python virtual environment in .venv"
python -m venv .venv

# Running this script only activates the venv for the script's own shell.
# Users should `source .venv/bin/activate` to enter the environment interactively.
. .venv/bin/activate

echo "[bootstrap] Upgrading pip and installing requirements"
python -m pip install --upgrade pip
if [ -f requirements-dev.txt ]; then
    pip install -r requirements-dev.txt
else
    echo "[bootstrap] WARNING: requirements-dev.txt not found. Install dependencies manually."
fi

if python -m playwright --version > /dev/null 2>&1; then
    echo "[bootstrap] Installing Playwright browsers"
    python -m playwright install --with-deps || true
else
    echo "[bootstrap] Playwright not installed; skipping browser install"
fi

echo "[bootstrap] Done. Activate the venv with: source .venv/bin/activate"
echo "[bootstrap] Note: the app and its tests need a reachable Postgres (DATABASE_URL) - run 'docker compose up -d db' or point DATABASE_URL at your own instance."