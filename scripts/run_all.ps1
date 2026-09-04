# NorthStar Chat - one-shot setup and run.
# Usage:  pwsh ./scripts/run_all.ps1 [-SkipSeed] [-Port 8000]

param(
    [switch]$SkipSeed,
    [switch]$SkipIngest,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
    Write-Host "[1/4] Installing requirements..." -ForegroundColor Cyan
    pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warning "pip install warnings (continuing)" }

    if (-not $SkipSeed) {
        Write-Host "[2/4] Seeding database (3 years of data)..." -ForegroundColor Cyan
        python database/seed_data.py
    } else { Write-Host "[2/4] Skipping seed (--SkipSeed)" -ForegroundColor DarkGray }

    if (-not $SkipIngest) {
        Write-Host "[3/4] Ingesting text documents..." -ForegroundColor Cyan
        python database/ingest_documents.py
    } else { Write-Host "[3/4] Skipping ingest (--SkipIngest)" -ForegroundColor DarkGray }

    if (-not $env:ANTHROPIC_API_KEY) {
        Write-Warning "ANTHROPIC_API_KEY not set. Running in offline mode."
        Write-Warning "To enable real LLM responses: `$env:ANTHROPIC_API_KEY = 'sk-ant-...'"
    } else {
        Write-Host "Anthropic key detected." -ForegroundColor Green
    }

    Write-Host "[4/4] Starting chat server on http://localhost:$Port ..." -ForegroundColor Cyan
    python -m uvicorn winning_architecture.server:app --port $Port
} finally {
    Pop-Location
}
