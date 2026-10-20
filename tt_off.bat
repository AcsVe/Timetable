@echo off
chcp 65001 >nul
title Timetable - Turn OFF
net session >nul 2>nul || (echo [X] Right-click this file and choose "Run as administrator". & pause & exit /b 1)
REM Stops 4.iajaward.org only - the other systems on this PC keep running
schtasks /end /tn "Timetable Website" >nul 2>nul
schtasks /change /tn "Timetable Website" /disable >nul 2>nul
echo.
echo   4.iajaward.org (timetable) is OFF (also after restarting the PC).
echo   The other systems are still running.
echo   To turn it back on: tt_on.bat (as administrator)
echo.
pause
