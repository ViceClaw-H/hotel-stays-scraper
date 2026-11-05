@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title Jalankan Pipeline Hotel Terpadu
echo ============================================================
echo   ANTIGRAVITY UNIFIED HOTEL ENGINE - DAILY RUNNER
echo ============================================================
"%PY_BIN%" build_index_hotel.py
pause
