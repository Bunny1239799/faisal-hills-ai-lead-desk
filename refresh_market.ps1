# refresh_market.ps1
# Runs market data ingestion and report generation
# Safe to schedule via Windows Task Scheduler

param(
    [string]$DataRawPath = "data/raw_chats",
    [string]$DbPath = "data/laya_gateway.db"
)

# === CONFIGURATION ===
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$IngestScript = Join-Path $ProjectRoot "tools\ingest_all.py"
$ReportScript = Join-Path $ProjectRoot "tools\market_report.py"

# === MAIN EXECUTION ===
Write-Host "=== Starting Market Data Refresh ==="

# Step 1: Run ingestion
Write-Host "Running market data ingestion..."
& python $IngestScript --raw-chat-dir $DataRawPath --db-path $DbPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "Market data ingestion failed"
    exit 1
}

# Step 2: Generate market report
Write-Host "Generating market report..."
& python $ReportScript --db-path $DbPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "Market report generation failed"
    exit 1
}

Write-Host "=== Market data refresh completed successfully ==="
