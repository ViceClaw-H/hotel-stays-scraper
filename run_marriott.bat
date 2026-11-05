@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"

title [GOLDEN STANDARD] Marriott 365-Day Harvester (Ghost CDP, 1 Worker)
echo ============================================================
echo   MARRIOTT 365-DAY HARVESTER (GHOST CDP, 1 WORKER - SAFE)
echo ============================================================
"%PY_BIN%" crawlers/marriott_fast_harvester.py --workers 1 --months 12
if errorlevel 1 (
    echo.
    echo [ERROR] Process stopped with an error.
)
pause
