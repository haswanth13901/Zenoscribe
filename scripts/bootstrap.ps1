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
if (Test-Path requirements-dev.txt) {
    python -m pip install -r requirements-dev.txt
} else {
    Write-Warning "requirements-dev.txt not found. Install dependencies manually."
}

try {
    python -m playwright --version | Out-Null
    Write-Host "[bootstrap] Installing Playwright browsers"
    python -m playwright install
} catch {
    Write-Warning "Playwright not installed; skipping browser install"
}

Write-Host "[bootstrap] Done. To use the venv interactively run: .\\.venv\\Scripts\\Activate.ps1"

# The app needs a reachable Postgres (DATABASE_URL) and Redis (REDIS_URL) -
# every request 503s without Redis, and the app won't start without
# Postgres. The fast test suite (pytest -q) doesn't need either - it uses
# in-process fakes - but running the app itself, or the integration suite
# (pytest -m integration), does. check_deps.py starts them via Docker if
# available and verifies both are actually accepting connections, rather
# than just telling you to go do it yourself.
python (Join-Path $PSScriptRoot "check_deps.py")