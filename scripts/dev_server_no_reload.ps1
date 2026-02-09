$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\.."
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Virtualenv not found at $python. Create it before running."
}

# No reload: most stable for long runs.
& $python -m uvicorn app.main:create_app --factory --log-level info
