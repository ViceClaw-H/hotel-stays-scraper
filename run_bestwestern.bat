@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title [GOLDEN STANDARD] Best Western Harvester
echo ============================================================
echo   BEST WESTERN HARVESTER
echo ============================================================
"%PY_BIN%" crawlers/bestwestern_harvester.py
if errorlevel 1 (
    echo.
    echo [ERROR] Process stopped with an error.
)
pause
