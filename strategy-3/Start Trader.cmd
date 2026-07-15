@echo off
setlocal
title Strategy 3 · UI:3002 · API:8002
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"
if errorlevel 1 pause
endlocal
