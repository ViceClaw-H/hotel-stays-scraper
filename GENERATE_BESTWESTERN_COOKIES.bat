@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" (
    echo [ERROR] Portable Python tidak ditemukan. Ekstrak ZIP secara lengkap,
    echo lalu jalankan file .bat dari folder hasil ekstrak tersebut.
    pause
    exit /b 1
)

title [SESSION GENERATOR] Best Western DataDome Clearance
color 0e
echo ============================================================
echo   BEST WESTERN DATADOME SESSION GENERATOR
echo   Launching Microsoft Edge on your screen...
echo ============================================================
echo.
"%PY_BIN%" "%~dp0crawlers\generate_bestwestern_cookies.py"
echo.
echo ============================================================
echo   Done! You may now run Best Western scraper without blocks.
echo ============================================================
pause
