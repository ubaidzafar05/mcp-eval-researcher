$ErrorActionPreference = "Stop"

Write-Host "[cloud-hive] Running provider smoke checks..." -ForegroundColor Cyan
poetry run python -m scripts.provider_smoke_minimal
