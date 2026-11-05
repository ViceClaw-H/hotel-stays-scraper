@echo off
cd /d "%~dp0"
title [GOLDEN STANDARD] Master Multi-Window Parallel Runner (12 Chains)
cls
echo ======================================================================
echo          ANTIGRAVITY UNIFIED HOTEL HARVESTER (GOLDEN STANDARD)
echo              LAUNCHING 12 CHAINS IN INDIVIDUAL TERMINAL WINDOWS
echo ======================================================================
echo.

start "1/12 Accor Harvester" /D "%~dp0" cmd.exe /c "call run_accor.bat"
start "2/12 IHG Harvester" /D "%~dp0" cmd.exe /c "call run_ihg.bat"
start "3/12 Hilton Harvester" /D "%~dp0" cmd.exe /c "call run_hilton.bat"
start "4/12 Marriott Harvester" /D "%~dp0" cmd.exe /c "call run_marriott.bat"
start "5/12 Hyatt Harvester" /D "%~dp0" cmd.exe /c "call run_hyatt.bat"
start "6/12 Wyndham Harvester" /D "%~dp0" cmd.exe /c "call run_wyndham.bat"
start "7/12 Swiss-Belhotel Harvester" /D "%~dp0" cmd.exe /c "call run_swissbel.bat"
start "8/12 Radisson Harvester" /D "%~dp0" cmd.exe /c "call run_radisson.bat"
start "9/12 Best Western Harvester" /D "%~dp0" cmd.exe /c "call run_bestwestern.bat"
start "10/12 Shangri-La Harvester" /D "%~dp0" cmd.exe /c "call run_shangrila.bat"
start "11/12 Langham Harvester" /D "%~dp0" cmd.exe /c "call run_langham.bat"
start "12/12 GHA Discovery Harvester" /D "%~dp0" cmd.exe /c "call run_gha.bat"

echo ======================================================================
echo [SUCCESS] Seluruh 12 chain telah diluncurkan di terminal terpisah!
echo ======================================================================
pause
