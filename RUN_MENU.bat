@echo off
cd /d "%~dp0"
set "PY_BIN=%~dp0portable_python\python.exe"
if not exist "%PY_BIN%" set "PY_BIN=python"
title [GOLDEN STANDARD] Master Harvester Menu (12 Chains)

:MENU
cls
echo ======================================================================
echo          ANTIGRAVITY UNIFIED HOTEL HARVESTER (GOLDEN STANDARD)
echo              PORTFOLIO: 12 GLOBAL CHAINS - PORTABLE EDITION
echo ======================================================================
echo   PILIH CHAIN YANG INGIN DI-SCRAPE:
echo.
echo    [1] Accor (ALL - Accor Live Limitless)
echo    [2] IHG (InterContinental, Holiday Inn, Crowne Plaza, voco, etc)
echo    [3] Hilton Honors (Conrad, Waldorf, DoubleTree, Hilton, etc)
echo    [4] Marriott Bonvoy (Ritz-Carlton, St Regis, Sheraton, W, etc)
echo    [5] Hyatt (World of Hyatt, Alila, Andaz, Park Hyatt, etc)
echo    [6] Wyndham Rewards (Days Inn, Ramada, Super 8, Wyndham, etc)
echo    [7] Swiss-Belhotel International
echo    [8] Radisson Hotel Group (Radisson Blu, RED, Park Inn, Park Plaza)
echo    [9] Best Western (BWH Hotels, WorldHotels, SureStay)
echo   [10] Shangri-La Circle
echo   [11] Langham (The Langham, Cordis, Eaton)
echo   [12] GHA DISCOVERY (Kempinski, Pan Pacific, Anantara, Capella)
echo.
echo   [C] REGENERATE ALL COOKIES (WAJIB: RUN PERTAMA / IP BERUBAH / 403-CAPTCHA)
echo   [H] REFRESH HILTON COOKIES (Akamai Anti-Block Helper)
echo   [M] REFRESH MARRIOTT COOKIES (Akamai Anti-Block Helper)
echo   [R] REFRESH RADISSON COOKIES (Akamai Anti-Block Helper)
echo   [B] REFRESH BEST WESTERN COOKIES (DataDome Helper)
echo   [V] AUDIT INTEGRITAS EVIDENCE (Cryptographic Parity & Value Replay)
echo   [S] STOP SEMUA SCRAPER (EMERGENCY STOP)
echo   [P] JALANKAN SEMUA BERSAMAAN (12 CHAIN CONCURRENT - 1 WINDOW DASHBOARD)
echo   [A] JALANKAN SEMUA BERURUTAN (FULL RUN 12 CHAIN SEQUENTIAL)
echo   [X] KELUAR
echo ======================================================================
set /p opt="Masukkan pilihan (1-12 / C / H / M / R / B / V / S / P / A / X): "

if /i "%opt%"=="1" call run_accor.bat & goto MENU
if /i "%opt%"=="2" call run_ihg.bat & goto MENU
if /i "%opt%"=="3" call run_hilton.bat & goto MENU
if /i "%opt%"=="4" call run_marriott.bat & goto MENU
if /i "%opt%"=="5" call run_hyatt.bat & goto MENU
if /i "%opt%"=="6" call run_wyndham.bat & goto MENU
if /i "%opt%"=="7" call run_swissbel.bat & goto MENU
if /i "%opt%"=="8" call run_radisson.bat & goto MENU
if /i "%opt%"=="9" call run_bestwestern.bat & goto MENU
if /i "%opt%"=="10" call run_shangrila.bat & goto MENU
if /i "%opt%"=="11" call run_langham.bat & goto MENU
if /i "%opt%"=="12" call run_gha.bat & goto MENU
if /i "%opt%"=="C" call REGENERATE_ALL_COOKIES.bat & goto MENU
if /i "%opt%"=="H" call GENERATE_HILTON_COOKIES.bat & goto MENU
if /i "%opt%"=="M" call GENERATE_MARRIOTT_COOKIES.bat & goto MENU
if /i "%opt%"=="R" call GENERATE_RADISSON_COOKIES.bat & goto MENU
if /i "%opt%"=="B" call GENERATE_BESTWESTERN_COOKIES.bat & goto MENU
if /i "%opt%"=="V" "%PY_BIN%" -m engine.verify_evidence_integrity & pause & goto MENU
if /i "%opt%"=="S" call STOP_ALL_SCRAPERS.bat & goto MENU
if /i "%opt%"=="P" call RUN_ALL_PARALLEL.bat & goto MENU
if /i "%opt%"=="A" goto RUN_ALL
if /i "%opt%"=="X" exit /b
goto MENU

:RUN_ALL
echo Memulai scraping seluruh 12 chain berurutan sesuai Golden Standard...
call run_swissbel.bat
call run_bestwestern.bat
call run_radisson.bat
call run_wyndham.bat
call run_ihg.bat
call run_accor.bat
call run_hyatt.bat
call run_hilton.bat
call run_marriott.bat
call run_shangrila.bat
call run_langham.bat
call run_gha.bat
pause
goto MENU
