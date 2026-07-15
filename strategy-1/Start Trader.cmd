@echo off
setlocal
title Strategy 1 · UI:3000 · API:8000
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"
if errorlevel 1 pause
endlocal
