param(
    [switch]$NoUi,
    [ValidateSet("minimal", "balanced", "full")]
    [string]$Profile = "minimal"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $RepoRoot ".dev"
$PidFile = Join-Path $StateDir "api.pid"
$StdoutLogFile = Join-Path $StateDir "api.out.log"
$StderrLogFile = Join-Path $StateDir "api.err.log"

Push-Location $RepoRoot

function Wait-ApiHealthy {
    param([int]$MaxAttempts = 30, [int]$SleepSeconds = 2)
    Write-Host "[cloud-hive] Waiting for API health on http://127.0.0.1:8080/health ..." -ForegroundColor Cyan
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -TimeoutSec 3 -UseBasicParsing
            if ($resp.StatusCode -eq 200) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds $SleepSeconds
        }
    }
    return $false
}

function Start-LocalBackend {
    param([string]$RuntimeProfile = "minimal")
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

    # Prevent stale process overlap.
    if (Test-Path $PidFile) {
        try {
            $existingPid = Get-Content $PidFile -ErrorAction Stop
            if ($existingPid) {
                Stop-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    Write-Host "[cloud-hive] Docker unavailable. Starting local backend (inprocess MCP)..." -ForegroundColor Yellow
    $env:RUNTIME_PROFILE = $RuntimeProfile
    $env:MCP_MODE = "inprocess"
    $env:INTERACTIVE_HITL = "false"
    $env:JUDGE_PROVIDER = "stub"

    $proc = Start-Process `
        -FilePath "poetry" `
        -ArgumentList @("run", "uvicorn", "service.api:app", "--host", "127.0.0.1", "--port", "8080") `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $StdoutLogFile `
        -RedirectStandardError $StderrLogFile `
        -PassThru

    Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii
}

function Start-DockerBackend {
    param([string]$RuntimeProfile = "minimal")
    Write-Host "[cloud-hive] Starting backend services via Docker (profile=$RuntimeProfile)..." -ForegroundColor Cyan
    $env:RUNTIME_PROFILE = $RuntimeProfile
    if ($RuntimeProfile -eq "minimal") {
        docker compose --profile core up -d web-mcp-http local-mcp-http app
        return
    }
    if ($RuntimeProfile -eq "balanced") {
        docker compose --profile core --profile distributed up -d web-mcp-http local-mcp-http redis celery-worker app
        return
    }
    docker compose --profile core --profile distributed --profile observability up -d web-mcp-http local-mcp-http redis celery-worker app prometheus grafana jaeger
}

$dockerAvailable = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    try {
        docker info | Out-Null
        $dockerAvailable = $true
    } catch {
        $dockerAvailable = $false
    }
}

if ($dockerAvailable) {
    Start-DockerBackend -RuntimeProfile $Profile
} else {
    if ($Profile -ne "minimal") {
        Write-Host "[cloud-hive] Docker is unavailable; forcing local minimal profile." -ForegroundColor Yellow
    }
    Start-LocalBackend -RuntimeProfile "minimal"
}

if (-not (Wait-ApiHealthy)) {
    Write-Host "[cloud-hive] API did not become healthy in time. Check: docker compose logs app" -ForegroundColor Red
    if ((Test-Path $StdoutLogFile) -or (Test-Path $StderrLogFile)) {
        Write-Host "[cloud-hive] Local backend logs (tail):" -ForegroundColor Yellow
        if (Test-Path $StdoutLogFile) {
            Write-Host "-- stdout --" -ForegroundColor DarkYellow
            Get-Content $StdoutLogFile -Tail 30
        }
        if (Test-Path $StderrLogFile) {
            Write-Host "-- stderr --" -ForegroundColor DarkYellow
            Get-Content $StderrLogFile -Tail 30
        }
    }
    exit 1
}

if ($NoUi) {
    Write-Host "[cloud-hive] Backend is up. Skipping UI because -NoUi was passed." -ForegroundColor Yellow
    Pop-Location
    exit 0
}

Write-Host "[cloud-hive] Starting web UI (http://localhost:3000)..." -ForegroundColor Cyan
Push-Location (Join-Path $RepoRoot "web-ui")
try {
    npm run dev
}
finally {
    Pop-Location
    Pop-Location
}
