@echo off
setlocal
title Strategy 2 · UI:3001 · API:8001
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"
if errorlevel 1 pause
endlocal
