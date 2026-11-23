# start_all.ps1
# Starts all services: Laya, Llama server, and the Laya Gateway console with browser

# === CONFIGURATION SECTION ===
# Path variables - update these to match your environment
$LayaPath = "D:\laya\.venv\Scripts\laya-serve.exe"
$LlamaServerPath = "D:\llama\llama-server.exe"
$LlamaModelPath = "D:\qwen2.5-1.5b-instruct-q4_k_m.gguf"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Environment variables for Laya
$LayaEnv = @{
    "LAYA_MODEL_PATH" = $LlamaModelPath
    "LAYA_SERVER_PORT" = "8000"
    "LAYA_GATEWAY_URL" = "http://localhost:8000"
}

# === FUNCTIONS ===
function Start-ProcessWithEnv {
    param(
        [string]$FilePath,
        [string]$Arguments,
        [hashtable]$Environment,
        [string]$WindowTitle
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.UseShellExecute = $true
    if ($Environment) {
        foreach ($key in $Environment.Keys) {
            $psi.Environment[$key] = $Environment[$key]
        }
    }
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal
    if ($WindowTitle) {
        $psi.Title = $WindowTitle
    }
    [System.Diagnostics.Process]::Start($psi) | Out-Null
}

function Wait-For-HealthCheck {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30,
        [string]$ServiceName
    )
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $response = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 5 -ErrorAction Stop
            if ($response.status -eq "ok") {
                Write-Host "[$ServiceName] Health check passed"
                return $true
            }
        } catch {
            # Service not ready yet
        }
        Start-Sleep -Seconds 2
    }
    Write-Warning "[$ServiceName] Health check failed after $TimeoutSeconds seconds"
    return $false
}

function Is-PortAlreadyInUse {
    param(
        [int]$Port
    )
    return (Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue) -ne $null
}

# === MAIN EXECUTION ===
param(
    [switch]$WithLaya,
    [switch]$WithLlama
)

Write-Host "=== Starting Laya Gateway Services ==="

# Start Laya service if requested
if ($WithLaya) {
    $layaPort = 8000
    if (Is-PortAlreadyInUse -Port $layaPort) {
        Write-Host "Laya service already running on port $layaPort, skipping..."
    } else {
        Write-Host "Starting Laya service..."
        Start-ProcessWithEnv `
            -FilePath $LayaPath `
            -Arguments "" `
            -Environment $LayaEnv `
            -WindowTitle "Laya Service"
        if (-not (Wait-For-HealthCheck -Url "http://localhost:$layaPort" -ServiceName "Laya")) {
            Write-Warning "Laya service may not have started correctly"
        }
    }
}

# Start Llama server if requested
if ($WithLlama) {
    $llamaPort = 8080
    if (Is-PortAlreadyInUse -Port $llamaPort) {
        Write-Host "Llama server already running on port $llamaPort, skipping..."
    } else {
        Write-Host "Starting Llama server..."
        Start-ProcessWithEnv `
            -FilePath $LlamaServerPath `
            -Arguments "-m `"$LlamaModelPath`" --port $llamaPort --host 0.0.0.0 --n-gpu-layers 35" `
            -WindowTitle "Llama Server"
        if (-not (Wait-For-HealthCheck -Url "http://localhost:$llamaPort" -ServiceName "Llama Server")) {
            Write-Warning "Llama server may not have started correctly"
        }
    }
}

# Start the gateway console and open browser
Write-Host "Starting Laya Gateway console..."
$consoleProcess = Start-Process -FilePath "python" -ArgumentList "-m app.server" -WorkingDirectory $ProjectRoot -PassThru

# Wait for gateway to be ready
if (Wait-For-HealthCheck -Url "http://localhost:8000" -ServiceName "Gateway") {
    Write-Host "Gateway is ready, opening browser..."
    Start-Process "http://localhost:8000"
} else {
    Write-Warning "Gateway may not have started correctly"
}

Write-Host "=== All services started ==="
Write-Host "Press Ctrl+C to stop all services"
try {
    while ($true) { Start-Sleep -Seconds 1 }
} finally {
    # Cleanup on exit
    Stop-Process -Id $consoleProcess.Id -Force
}
