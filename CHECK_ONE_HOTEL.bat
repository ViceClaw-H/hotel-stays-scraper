@echo off
chcp 65001 >nul
title Cek 1 hotel per rantai
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
echo.
echo  Cek 1 hotel per rantai (di salinan sementara; database Anda tidak diubah).
echo  Pemakaian:   CHECK_ONE_HOTEL.bat swissbel
echo               CHECK_ONE_HOTEL.bat all
echo               CHECK_ONE_HOTEL.bat --list
echo.
if "%~1"=="" (
  "%PY_BIN%" "%~dp0tools\check_one_hotel.py" --list
) else (
  "%PY_BIN%" "%~dp0tools\check_one_hotel.py" %*
)
pause
