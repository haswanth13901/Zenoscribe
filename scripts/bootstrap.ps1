Set-StrictMode -Version Latest

Write-Host "[bootstrap] Creating Python virtual environment in .venv"
python -m venv .venv

Write-Host "[bootstrap] Activating venv for this script"
# Activate only affects the running process. To use interactively, run:
#  .\.venv\Scripts\Activate.ps1
$env:VIRTUAL_ENV = (Resolve-Path .venv).Path
$env:PATH = "$env:VIRTUAL_ENV\Scripts;" + $env:PATH

Write-Host "[bootstrap] Upgrading pip and installing requirements"
python -m pip install --upgrade pip
if (Test-Path requirements.txt) {
    python -m pip install -r requirements.txt
} else {
    Write-Warning "requirements.txt not found. Install dependencies manually."
}

try {
    python -m playwright --version | Out-Null
    Write-Host "[bootstrap] Installing Playwright browsers"
    python -m playwright install
} catch {
    Write-Warning "Playwright not installed; skipping browser install"
}

Write-Host "[bootstrap] Done. To use the venv interactively run: .\\.venv\\Scripts\\Activate.ps1"
Write-Host "[bootstrap] Note: the app and its tests need a reachable Postgres (DATABASE_URL) - run 'docker compose up -d db' or point DATABASE_URL at your own instance."