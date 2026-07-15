@echo off
setlocal
title Strategy 4 · UI:3003 · API:8003
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"
if errorlevel 1 pause
endlocal
