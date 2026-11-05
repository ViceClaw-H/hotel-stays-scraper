@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title GHA DISCOVERY - price harvester
echo ============================================================
echo   GHA DISCOVERY - HARGA (Best Available Rate, sudah termasuk pajak)
echo   Daftar hotel diambil dulu bila database belum punya hotel GHA.
echo   Tambahan opsi: --limit 5   --dates 24   --headless
echo ============================================================
"%PY_BIN%" crawlers/gha_harvester.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Selesai dengan error. Baca pesan di atas ^(tidak ada harga yang dikarang^).
)
pause
