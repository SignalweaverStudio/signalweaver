# run.ps1 — SignalWeaver backend launcher

Set-Location -Path $PSScriptRoot

$venvActivate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$env:PYTHONPATH = (Join-Path $PSScriptRoot "src")

python -m uvicorn app.main:app --reload
