@echo off
title Run Automated Test Suite
"%~dp0portable_python\python.exe" -m unittest discover "%~dp0tests"
pause
