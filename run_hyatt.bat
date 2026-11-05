@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title [GOLDEN STANDARD] Hyatt 365-Day Harvester (Ghost CDP, 2 Workers)
echo ============================================================
echo   HYATT 365-DAY HARVESTER (GHOST CDP, 2 WORKERS)
echo ============================================================
"%PY_BIN%" crawlers/hyatt_avail_days_harvester.py --workers 2 --months 12
if errorlevel 1 (
    echo.
    echo [ERROR] Process stopped with an error.
)
pause
