param(
    [switch]$SkipFrontend,
    [string]$IndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"

Write-Host "Installing backend dependencies with uv..." -ForegroundColor Cyan
Push-Location $backendDir
try {
    uv sync --extra dev --default-index $IndexUrl
    uv run python -c "import demucs, torch, basic_pitch; print('Backend runtime OK')"
}
finally {
    Pop-Location
}

if (-not $SkipFrontend) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    Push-Location $frontendDir
    try {
        npm ci
        npm run build
    }
    finally {
        Pop-Location
    }
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg was not found in PATH. Install it before separating audio."
}

Write-Host ""
Write-Host "Setup complete. Run .\start.ps1 and open http://127.0.0.1:8000" -ForegroundColor Green
