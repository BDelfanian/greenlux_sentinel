# Local dev environment bootstrap (Windows/PowerShell).
# Run from the repo root: .\scripts\setup_env.ps1

python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -e ".[dev]"

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example — fill in Azure connection strings and API keys."
}

Write-Host "Done. Activate with: .\.venv\Scripts\Activate.ps1"
