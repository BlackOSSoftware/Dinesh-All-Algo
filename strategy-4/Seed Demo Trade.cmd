@echo off
title Strategy 4 · Seed Demo Trade
cd /d "%~dp0backend"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\seed_demo_breakout_trade.py"
) else (
  python "scripts\seed_demo_breakout_trade.py"
)
echo.
pause
