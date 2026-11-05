@echo off
title Master Session Cookie Generator (Hilton, Marriott, Best Western, Radisson)
cd /d "%~dp0"
cls
echo ======================================================================
echo          MASTER SESSION COOKIE GENERATOR - ALL PROTECTED CHAINS
echo ======================================================================
echo.
echo Script ini memandu regenerasi cookie secara berurutan untuk 4 jaringan
echo yang dilindungi sistem anti-bot (Akamai / DataDome):
echo   1. Hilton Honors        (Akamai Botman)
echo   2. Marriott Bonvoy      (Akamai EdgeSuite)
echo   3. Best Western         (DataDome)
echo   4. Radisson Hotel Group (Akamai Shield)
echo.
echo BROWSER AKAN TERBUKA SECARA BERGANTIAN.
echo Silakan selesaikan centang/challenge jika muncul di layar.
echo ======================================================================
echo.
pause

echo.
echo [1/4] MENJALANKAN GENERATOR COOKIE HILTON...
call GENERATE_HILTON_COOKIES.bat

echo.
echo [2/4] MENJALANKAN GENERATOR COOKIE MARRIOTT...
call GENERATE_MARRIOTT_COOKIES.bat

echo.
echo [3/4] MENJALANKAN GENERATOR COOKIE BEST WESTERN...
call GENERATE_BESTWESTERN_COOKIES.bat

echo.
echo [4/4] MENJALANKAN GENERATOR COOKIE RADISSON...
call GENERATE_RADISSON_COOKIES.bat

echo.
echo ======================================================================
echo    SELURUH SESI COOKIE TELAH SELESAI DI-GENERATE!
echo    Seluruh scraper kini siap dijalankan tanpa hambatan Akamai/DataDome.
echo ======================================================================
echo.
pause
