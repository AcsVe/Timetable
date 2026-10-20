@echo off
cd /d "%~dp0"
net session >nul 2>nul || (echo [X] Run as administrator. & pause & exit /b 1)
schtasks /end /tn "Timetable Website" >nul 2>nul
schtasks /delete /f /tn "Timetable Website" >nul 2>nul
schtasks /delete /f /tn "Timetable Hourly Backup" >nul 2>nul
schtasks /delete /f /tn "Timetable Failover Watchdog" >nul 2>nul
echo Stopped and removed the Timetable tasks.
pause
