@echo off
title EMERGENCY STOP - Hotel Scrapers
cd /d "%~dp0"
echo ========================================================
echo        EMERGENCY STOP - HENTIKAN SELURUH SCRAPER
echo ========================================================
echo.
echo Menghentikan seluruh proses scraper dan worker latar belakang...
echo.
if exist "portable_python\python.exe" (
    portable_python\python.exe crawlers\emergency_stop.py
) else (
    python crawlers\emergency_stop.py
)
echo.
pause
