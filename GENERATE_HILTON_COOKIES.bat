@echo off
title Hilton Honors Cookie Generator
cd /d "%~dp0"
echo ========================================================
echo       HILTON HONORS SESSION COOKIE GENERATOR
echo ========================================================
echo.
echo Menjalankan Autonomous / Interactive Cookie Generator...
echo.
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" (
    echo [ERROR] Portable Python tidak ditemukan. Ekstrak ZIP secara lengkap,
    echo lalu jalankan file .bat dari folder hasil ekstrak tersebut.
    pause
    exit /b 1
)
"%PY_BIN%" "%~dp0crawlers\generate_hilton_cookies.py" %*
echo.
pause
