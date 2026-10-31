# Runs the automated checks (virtual drones, no-fly zones, routes, licences, every page's scripts).
# Usage:  powershell -ExecutionPolicy Bypass -File run_tests.ps1
$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv-build\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
& $python -m pytest @args
exit $LASTEXITCODE
