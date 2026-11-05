@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title [GOLDEN STANDARD] Master Harvester (12 Chains Concurrent)
cls
"%PY_BIN%" crawlers\master_concurrent_runner.py
pause
