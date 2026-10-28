@echo off
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
cd /d %~dp0..
python --version > .engineering-bootstrap\tmp\sweep6.log
python -m pytest tests -q --tb=no -rf -rE -p no:cacheprovider >> .engineering-bootstrap\tmp\sweep6.log 2>&1
echo exit=%ERRORLEVEL% > .engineering-bootstrap\tmp\sweep6.exitcode
