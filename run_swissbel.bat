@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title [GOLDEN STANDARD] Swiss-Belhotel 365-Day Rate Harvester
echo ============================================================
echo   SWISS-BELHOTEL 365-DAY RATE HARVESTER (HOTELCHAMP IBE)
echo ============================================================
"%PY_BIN%" crawlers/swissbel_harvester.py
if errorlevel 1 (
    echo.
    echo [ERROR] Process stopped with an error.
)
pause
