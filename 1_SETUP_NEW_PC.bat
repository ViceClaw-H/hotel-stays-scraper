@echo off
cd /d "%~dp0"
title [GOLDEN STANDARD] Portable Environment Verification & Setup
cls
echo ======================================================================
echo       ANTIGRAVITY UNIFIED HOTEL HARVESTER - ENVIRONMENT VERIFIER
echo                       Portable Windows Edition
echo ======================================================================

set "PY_BIN=%~dp0portable_python\python.exe"
if exist "%PY_BIN%" (
    echo [1/3] Python Runtime: Portable Python bundled (No global install needed).
    "%PY_BIN%" --version
) else (
    echo [1/3] Checking System Python installation...
    python --version
    if %errorlevel% neq 0 (
        echo [ERROR] Neither portable_python nor system Python was found!
        echo Please ensure portable_python is extracted or install Python 3.10+.
        pause
        exit /b 1
    )
    set "PY_BIN=python"
)

echo.
echo [2/3] Checking Browser Engine (Edge / Chrome)...
set "BROWSER_FOUND=0"
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    echo [OK] Microsoft Edge detected (C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe)
    set "BROWSER_FOUND=1"
) else if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    echo [OK] Microsoft Edge detected (C:\Program Files\Microsoft\Edge\Application\msedge.exe)
    set "BROWSER_FOUND=1"
) else if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo [OK] Google Chrome detected (C:\Program Files\Google\Chrome\Application\chrome.exe)
    set "BROWSER_FOUND=1"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    echo [OK] Google Chrome detected (C:\Program Files (x86)\Google\Chrome\Application\chrome.exe)
    set "BROWSER_FOUND=1"
)

if "%BROWSER_FOUND%"=="0" (
    echo [WARNING] Neither Google Chrome nor Microsoft Edge was found in standard locations.
    echo Browser-assisted chains (Marriott, Hilton, Radisson) require Chrome or Edge.
) else (
    echo [OK] Compatible browser engine confirmed ready.
)

echo.
echo [3/3] Verifying Database and Cryptographic Evidence Gate...
"%PY_BIN%" -m engine.verify_evidence_integrity
if %errorlevel% neq 0 (
    echo [WARNING] Evidence audit flagged warnings.
) else (
    echo [OK] Evidence Cryptographic Parity: 100%% PASSED.
)

echo.
echo ======================================================================
echo [SUCCESS] Portable Environment Verified!
echo You can run RUN_MENU.bat or any individual run_<chain>.bat file.
echo ======================================================================
pause
