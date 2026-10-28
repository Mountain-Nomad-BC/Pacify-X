$env:Path = [Environment]::GetEnvironmentVariable("Path","User") + ";" + $env:Path
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pytest tests/test_structural_integrity.py tests/test_test_profiles.py tests/test_typed_operational_surface_inventory.py tests/test_usage_memory.py tests/test_workflow_studio.py -q --tb=line -p no:cacheprovider 2>&1 | Out-String -Width 400 | Set-Content -Encoding UTF8 .engineering-bootstrap/tmp/coupled4.txt
$LASTEXITCODE | Set-Content .engineering-bootstrap/tmp/coupled4.exitcode
