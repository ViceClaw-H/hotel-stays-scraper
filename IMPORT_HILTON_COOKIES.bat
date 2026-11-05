@echo off
title Hilton Honors Cookie Importer
cd /d "%~dp0"
echo ========================================================
echo       HILTON HONORS MANUAL COOKIE IMPORTER
echo ========================================================
echo.
echo Alat ini memungkinkan Anda memasukkan cookie Hilton secara langsung
echo dari Chrome biasa (copy-paste) jika bot terkena blokir Akamai.
echo.
if exist "portable_python\python.exe" (
    portable_python\python.exe crawlers\import_hilton_cookies.py %*
) else (
    python crawlers\import_hilton_cookies.py %*
)
echo.
pause
