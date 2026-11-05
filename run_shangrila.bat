@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title [GOLDEN STANDARD] Shangri-La 365-Day Harvester
echo ============================================================
echo   SHANGRI-LA 365-DAY HARVESTER
echo ============================================================
"%PY_BIN%" crawlers/shangrila_master_365_and_percentiles_crawler.py
if errorlevel 1 (
    echo.
    echo [ERROR] Process stopped with an error.
)
pause
