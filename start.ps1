param(
    [switch]$Reload,
    [switch]$RebuildFrontend
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$python = Join-Path $backendDir ".venv\Scripts\python.exe"
$frontendIndex = Join-Path $frontendDir "dist\index.html"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend environment is missing. Run .\setup.ps1 first."
}

if ($RebuildFrontend -or -not (Test-Path -LiteralPath $frontendIndex)) {
    Push-Location $frontendDir
    try {
        npm run build
    }
    finally {
        Pop-Location
    }
}

Push-Location $backendDir
try {
    $arguments = @("-m", "uvicorn", "app.main:app", "--port", "8000")
    if ($Reload) {
        $arguments += "--reload"
    }
    Write-Host "Fretline: http://127.0.0.1:8000" -ForegroundColor Green
    & $python @arguments
}
finally {
    Pop-Location
}
