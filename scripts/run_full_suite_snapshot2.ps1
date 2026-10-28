$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
Set-Location $PSScriptRoot\..
python -m pytest tests -q --tb=no -rf -rE -p no:cacheprovider 2>&1 | Out-String -Width 400 | Set-Content -Encoding UTF8 .agentic_engineering_os_px/validation/python-suite-2026-10-06-rerun2.txt
$LASTEXITCODE | Set-Content .agentic_engineering_os_px/validation/python-suite-2026-10-06-rerun2.exitcode
