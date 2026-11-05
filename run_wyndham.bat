@echo off

cd /d "%~dp0"

set "PY_BIN=%~dp0portable_python\python.exe"

if not exist "%PY_BIN%" set "PY_BIN=python"

title [GOLDEN STANDARD] Wyndham 365-Day Harvester (4 Workers)

echo ============================================================

echo   WYNDHAM 365-DAY HARVESTER (4 WORKERS)

echo ============================================================

"%PY_BIN%" crawlers/wyndham_stream_harvester.py --workers 4 --max-rps 2.5

if errorlevel 1 (

    echo.

    echo [ERROR] Process stopped with an error.

)

pause

