$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
Set-Location $PSScriptRoot\..
python -m pytest tests -q --tb=no -p no:cacheprovider --junitxml=.agentic_engineering_os_px/validation/junit-2026-10-06-v3.xml 2>&1 | Out-String -Width 400 | Set-Content -Encoding UTF8 .agentic_engineering_os_px/validation/python-suite-2026-10-06-v3.txt
$LASTEXITCODE | Set-Content .agentic_engineering_os_px/validation/python-suite-2026-10-06-v3.exitcode
