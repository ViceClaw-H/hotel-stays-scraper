@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title [GOLDEN STANDARD] Accor ALL Harvester (1 Worker)
echo ============================================================
echo   ACCOR ALL HARVESTER (1 WORKER)
echo ============================================================
"%PY_BIN%" crawlers/accor_fast_harvester.py --num-workers 1 --days 120
if errorlevel 1 (
    echo.
    echo [ERROR] Process stopped with an error.
)
pause
