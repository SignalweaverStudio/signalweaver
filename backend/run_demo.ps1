# SignalWeaver demo launcher (from backend\)
$ErrorActionPreference = "Stop"

$backendRoot = "C:\Users\verti\projects\signalweaver\backend"
Set-Location $backendRoot

# Go to src (where app.main lives)
$src = Join-Path $backendRoot "src"
if (!(Test-Path $src)) { throw "Can't find src folder at: $src" }
Set-Location $src

# Activate venv
$activate = Join-Path $backendRoot ".venv\Scripts\Activate.ps1"
if (!(Test-Path $activate)) { throw "Can't find venv activate script at: $activate" }
& $activate

Write-Host ""
Write-Host "✅ Venv:" (Get-Command python).Source
Write-Host "✅ Starting SignalWeaver..."
Write-Host "   Health: http://127.0.0.1:8000/health"
Write-Host "   Docs:   http://127.0.0.1:8000/docs"
Write-Host ""

uvicorn app.main:app --reload
