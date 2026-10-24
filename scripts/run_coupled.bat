@echo off
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
cd /d %~dp0..
python -m pytest tests/test_structural_integrity.py tests/test_test_profiles.py tests/test_typed_operational_surface_inventory.py tests/test_usage_memory.py tests/test_workflow_studio.py -q --tb=line -p no:cacheprovider > .engineering-bootstrap\tmp\coupled5.log 2>&1
echo exit=%ERRORLEVEL% > .engineering-bootstrap\tmp\coupled5.exitcode
