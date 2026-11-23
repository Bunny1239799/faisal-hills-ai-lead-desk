<#
.SYNOPSIS
    Build the share-ready zip for evaluation / showcase platforms.

.DESCRIPTION
    Copies ONLY an explicit include-list into a staging folder, writes a
    MANIFEST, and compresses it. Nothing else can leak in:

      * no databases (*.db) - the demo fact DB, the conversation stores and
        the root raw archive all stay on the owner machine;
      * no master inventory CSV / JSONL (business data);
      * no backups, logs, __pycache__, .venv, .aider artifacts, archive.

    The default output is D:\FaisalHillsAILeadDesk\showcase_package.

.PARAMETER OutDir
    Where the zip is written. Default: D:\FaisalHillsAILeadDesk\showcase_package

.PARAMETER IncludeMasterData
    Opt-in ONLY: also include market\master_inventory.csv (the 374-plot
    dataset in CSV form). Leave OFF for any public upload.

.EXAMPLE
    .\tools\build_upload_package.ps1
#>
[CmdletBinding()]
param(
    [string]$OutDir = "D:\FaisalHillsAILeadDesk\showcase_package",
    [switch]$IncludeMasterData
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot            # repository root
$stamp = Get-Date -Format "yyyyMMdd"
$name = "faisal-hills-ai-lead-desk-v1.0.0-$stamp"
$stage = Join-Path $env:TEMP $name
$zipPath = Join-Path $OutDir "$name.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage, $OutDir | Out-Null

function Copy-Tree {
    param([string]$Relative, [string[]]$ExcludeDirs = @(), [string[]]$ExcludeFiles = @())
    $src = Join-Path $root $Relative
    if (-not (Test-Path $src)) { return }
    $dst = Join-Path $stage $Relative
    $item = Get-Item $src
    if ($item.PSIsContainer) {
        Get-ChildItem $src -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring($root.Length + 1)
            $skip = $false
            foreach ($d in $ExcludeDirs) {
                if ($rel -like "$d\*") { $skip = $true }
            }
            foreach ($f in $ExcludeFiles) {
                if ($_.Name -like $f) { $skip = $true }
            }
            if (-not $skip) {
                $target = Join-Path $stage $rel
                New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
                Copy-Item $_.FullName $target
            }
        }
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
        Copy-Item $src $dst
    }
}

# --- top-level files -------------------------------------------------------
foreach ($f in @("README.md", "requirements.txt", "pytest.ini", "conftest.py",
                 "start_operator_desk.bat")) {
    Copy-Tree -Relative $f
}

# --- curated documentation + screenshots ----------------------------------
foreach ($f in @("docs\PROJECT_OVERVIEW.md", "docs\VERIFICATION.md",
                 "docs\UPLOAD_GUIDE.md", "docs\DEMO_SCRIPT.md",
                 "docs\BACKUP_POLICY.md", "docs\m12_api_contract.json")) {
    Copy-Tree -Relative $f
}
Copy-Tree -Relative "docs\screenshots"

# --- source ---------------------------------------------------------------
Copy-Tree -Relative "app" -ExcludeDirs @("app\__pycache__") -ExcludeFiles @("*.pyc", "*.bak*")
Copy-Tree -Relative "market" -ExcludeDirs @("market\__pycache__") -ExcludeFiles @("*.pyc", "*.bak*")
if (-not $IncludeMasterData) {
    Remove-Item (Join-Path $stage "market\master_inventory.csv") -Force -ErrorAction SilentlyContinue
}
# data: ONLY the three code files - every runtime store and subdir stays out
foreach ($f in @("data\db.py", "data\demo_seed.py", "data\schema.sql")) {
    Copy-Tree -Relative $f
}
Copy-Tree -Relative "tests" -ExcludeDirs @("tests\__pycache__") -ExcludeFiles @("*.pyc", "*.bak*")
foreach ($f in @("tools\reset_demo_state.py", "tools\build_upload_package.ps1",
                 "tools\evaluate_fh_queries.py")) {
    Copy-Tree -Relative $f
}

# --- evaluation reports (evidence of the baseline) ------------------------
Copy-Tree -Relative "evaluation\reports" -ExcludeFiles @("*.db", "*.bak*")

# --- manifest -------------------------------------------------------------
$files = Get-ChildItem $stage -Recurse -File
$manifest = @()
$manifest += "Faisal Hills AI Lead Desk - share package"
$manifest += "Built: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$manifest += "Files: $($files.Count)   Size: $([math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 2)) MB"
$manifest += ""
$manifest += "DELIBERATELY EXCLUDED (privacy by design):"
$manifest += "  - every *.db (demo fact DB, conversation/lead stores, raw archive)"
$manifest += "  - market\master_inventory.csv (business pricing data) unless -IncludeMasterData"
$manifest += "  - backups, logs, __pycache__, .venv, .aider artifacts, archive\, .github\"
$manifest += "  - internal working notes (CHECKPOINT/DECISIONS/DEFECTS/PROGRESS/...)"
$manifest += ""
$manifest += "CONTENTS:"
$manifest += ($files | ForEach-Object {
    $_.FullName.Substring($stage.Length + 1)
} | Sort-Object)
$manifest -join "`r`n" | Out-File -Encoding utf8 (Join-Path $stage "MANIFEST.txt")

# --- zip ------------------------------------------------------------------
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -CompressionLevel Optimal
$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash
Remove-Item $stage -Recurse -Force

Write-Host ""
Write-Host "Package : $zipPath"
Write-Host "Files   : $($files.Count)"
Write-Host "Size    : $([math]::Round((Get-Item $zipPath).Length / 1MB, 2)) MB"
Write-Host "SHA256  : $hash"
Write-Host "Master data included: $($IncludeMasterData.IsPresent)"
