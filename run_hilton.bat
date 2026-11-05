@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title Hilton Harvester (Ghost CDP, 1 worker)
echo ============================================================
echo   HILTON HARVESTER (GHOST CDP, 1 WORKER - 2 WORKERS TRIGGERED REPEATED AKAMAI CHALLENGES)
echo ============================================================
"%PY_BIN%" crawlers/hilton_fast_harvester.py --workers 1 --months 3 --offscreen
if errorlevel 1 (
    echo.
    echo [ERROR] Process stopped with an error.
)
pause
