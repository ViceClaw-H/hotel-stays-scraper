@echo off
title Pre-Flight Readiness Check
"%~dp0portable_python\python.exe" "%~dp0tools\check_readiness.py"
pause
