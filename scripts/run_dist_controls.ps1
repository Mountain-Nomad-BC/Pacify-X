$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
Set-Location $PSScriptRoot\..
param_test_file = $args
python -m pytest tests/test_release_distribution_controls.py -q --tb=line -p no:cacheprovider 2>&1 | Out-String -Width 400 | Set-Content -Encoding UTF8 .agentic_engineering_os_px/validation/dist-controls.txt
$LASTEXITCODE | Set-Content .agentic_engineering_os_px/validation/dist-controls.exitcode
