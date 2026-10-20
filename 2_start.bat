@echo off
chcp 65001 >nul
title Timetable - running (close this window to stop)
cd /d "%~dp0"
call scripts\find_python.bat
set DATABASE_URL=
set PYTHONUTF8=1
if not exist .env (echo [X] Run 1_setup.bat first & pause & exit /b 1)
echo.
echo   Local : http://localhost:8004/
echo   Public: https://4.iajaward.org/
echo   Close this window to stop.
echo.
"%PY%" serve.py
pause
