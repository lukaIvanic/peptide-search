$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\.."
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Virtualenv not found at $python. Create it before running."
}

# Use factory mode + reload delay to avoid reload race issues.
& $python -m uvicorn app.main:create_app --factory --reload --reload-delay 0.5 --log-level info
