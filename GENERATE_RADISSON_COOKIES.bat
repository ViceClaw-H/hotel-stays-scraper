@echo off
setlocal
cd /d "%~dp0"
title Radisson Hotel Group - Cookie Generator
cls
echo ======================================================================
echo       RADISSON HOTEL GROUP - AKAMAI COOKIE GENERATOR
echo ======================================================================
echo.
echo Script ini akan meluncurkan jendela browser untuk mendapatkan cookie
echo Akamai valid agar crawler Radisson dapat berjalan tanpa terkena blokir.
echo.

set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" (
    echo [ERROR] Portable Python tidak ditemukan. Ekstrak ZIP secara lengkap,
    echo lalu jalankan file .bat dari folder hasil ekstrak tersebut.
    pause
    exit /b 1
)
"%PY_BIN%" "%~dp0crawlers\generate_radisson_cookies.py"

echo.
echo Selesai. Tekan tombol apa saja untuk keluar...
pause >nul
