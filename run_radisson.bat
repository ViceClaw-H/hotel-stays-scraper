@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title Radisson Hotel Group - price harvester
echo ============================================================
echo   RADISSON - HARGA (tarif publik room-only, sudah termasuk pajak)
echo   Tidak perlu cookie atau login: jendela browser dibuka otomatis.
echo   Tambahan opsi: --limit 5   --dates 24   --discover   --headless
echo ============================================================
"%PY_BIN%" crawlers/radisson_harvester.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Selesai dengan error. Baca pesan di atas ^(tidak ada harga yang dikarang^).
)
pause
