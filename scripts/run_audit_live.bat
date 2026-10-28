@echo off
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
cd /d %~dp0..
python .engineering-bootstrap\tmp\run_audit_live.py > .engineering-bootstrap\tmp\audit_live2.log 2>&1
echo exit=%ERRORLEVEL% > .engineering-bootstrap\tmp\audit_live2.exitcode
