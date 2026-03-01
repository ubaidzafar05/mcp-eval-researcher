$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $RepoRoot ".dev"
$PidFile = Join-Path $StateDir "api.pid"

Write-Host "[cloud-hive] Stopping backend services..." -ForegroundColor Cyan
if (Get-Command docker -ErrorAction SilentlyContinue) {
    try {
        docker compose down
    } catch {}
}

if (Test-Path $PidFile) {
    try {
        $pidValue = Get-Content $PidFile -ErrorAction Stop
        if ($pidValue) {
            Stop-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
            Write-Host "[cloud-hive] Stopped local backend PID $pidValue" -ForegroundColor Yellow
        }
    } catch {}
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# Also clean up stale local uvicorn API processes from previous runs.
try {
    $candidates = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match "python" -and
            $_.CommandLine -match "uvicorn" -and
            $_.CommandLine -match "service\.api:app"
        }
    foreach ($proc in $candidates) {
        try {
            Stop-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue
            Write-Host "[cloud-hive] Stopped stale API process PID $($proc.ProcessId)" -ForegroundColor Yellow
        } catch {}
    }
} catch {}
