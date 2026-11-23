# backup.ps1
# Creates timestamped backups of SQLite database and raw chats
# Keeps only the last 14 backups

param(
    [string]$BackupRoot = "D:\backups\laya-gateway",
    [string]$DbPath = "data/laya_gateway.db",
    [string]$RawChatsPath = "data/raw_chats"
)

# === MAIN EXECUTION ===
Write-Host "=== Starting Backup Process ==="

# Create backup root if it doesn't exist
if (-not (Test-Path $BackupRoot)) {
    New-Item -ItemType Directory -Path $BackupRoot | Out-Null
}

# Generate timestamp for backup folder
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $BackupRoot "backup_$timestamp"

# Create backup directory
New-Item -ItemType Directory -Path $backupDir | Out-Null

# Backup SQLite database
if (Test-Path $DbPath) {
    Write-Host "Backing up database..."
    Copy-Item -Path $DbPath -Destination (Join-Path $backupDir "laya_gateway.db")
} else {
    Write-Warning "Database file not found at $DbPath"
}

# Backup raw chats directory
if (Test-Path $RawChatsPath) {
    Write-Host "Backing up raw chats..."
    Copy-Item -Path $RawChatsPath -Destination (Join-Path $backupDir "raw_chats") -Recurse
} else {
    Write-Warning "Raw chats directory not found at $RawChatsPath"
}

# Cleanup old backups (keep only last 14)
Write-Host "Cleaning up old backups..."
$backups = Get-ChildItem -Path $BackupRoot -Filter "backup_*" | 
           Sort-Object Name -Descending
if ($backups.Count -gt 14) {
    $backupsToDelete = $backups[14..($backups.Count-1)]
    foreach ($backup in $backupsToDelete) {
        Write-Host "Removing old backup: $($backup.Name)"
        Remove-Item -Path $backup.FullName -Recurse -Force
    }
}

Write-Host "=== Backup completed successfully ==="
Write-Host "Backup stored at: $backupDir"
