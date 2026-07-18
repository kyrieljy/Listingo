param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$BackendHost = "0.0.0.0",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$projectRoot = Resolve-Path $ProjectRoot
Set-Location $projectRoot

if (-not (Test-Path (Join-Path $projectRoot ".venv\Scripts\python.exe"))) {
    python -m venv .venv
}

Write-Host "Installing backend dependencies..."
& ".\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt

Write-Host "Starting backend and frontend... (Ctrl+C stop)"
Start-Process -NoNewWindow -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @(
    "-m", "uvicorn", "backend.app.main:app",
    "--host", $BackendHost, "--port", $BackendPort
)

Set-Location (Join-Path $projectRoot "frontend")
npm install
npm run build
npm run preview -- --host 0.0.0.0 --port $FrontendPort
