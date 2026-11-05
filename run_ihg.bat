@echo off

cd /d "%~dp0"

set "PY_BIN=%~dp0portable_python\python.exe"

if not exist "%PY_BIN%" set "PY_BIN=python"

title [GOLDEN STANDARD] IHG 365-Day Harvester (3 Workers - Rate 1.5/s)

echo ============================================================

echo   IHG 365-DAY HARVESTER (3 WORKERS - RATE 1.5/s)

echo ============================================================

"%PY_BIN%" crawlers/ihg_calendar_harvester.py --workers 3 --rate 1.5

if errorlevel 1 (

    echo.

    echo [ERROR] Process stopped with an error.

)

pause

