@echo off
chcp 65001 >nul
title Timetable - First time setup
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=
set DATABASE_URL=
set PYTHONUTF8=1
echo =====================================================
echo   School Timetable (4.iajaward.org) - setup on this PC
echo =====================================================
where python >nul 2>nul || (echo [X] Python is not installed. Install Python 3.12 64-bit from python.org with "Add python.exe to PATH". & pause & exit /b 1)
if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv venv || (echo [X] Could not create venv & pause & exit /b 1)
)
call scripts\find_python.bat
echo Installing packages (a few minutes the first time)...
"%PY%" -m pip install -q --disable-pip-version-check --timeout 60 -r requirements.txt || (echo [X] pip install failed - check the internet & pause & exit /b 1)

if not exist .env (
  "%PY%" ops\setup_local.py || (pause & exit /b 1)
) else (
  echo .env already exists - keeping it. To change settings run: venv\Scripts\python ops\setup_local.py
)

echo.
echo Checking PostgreSQL and the database...
"%PY%" -c "import sys; sys.path.insert(0,'ops'); from common import load_env; load_env(); import pgtools; pgtools.ensure_database(pgtools.db_url()); print('  OK')" || (pause & exit /b 1)

echo.
set "IMPORT=n"
set /p "IMPORT=Copy ALL data from the Neon cloud database (Render) now? This REPLACES the data on this PC. (y/N): "
if /i "%IMPORT%"=="y" "%PY%" ops\import_neon.py --yes

echo.
echo Creating / upgrading the database tables...
"%PY%" serve.py --prepare || (echo [X] Database setup failed - see logs\server.log & pause & exit /b 1)
"%PY%" ops\first_admin.py

echo.
echo Connecting 4.iajaward.org to this PC (Cloudflare)...
"%PY%" ops\cf.py setup

echo.
echo =====================================================
echo   Setup finished.
echo   Next: 3_autostart.bat (right-click - Run as administrator)
echo         to start it with Windows + hourly backup + watchdog
echo   Test now: 2_start.bat then open http://localhost:8004/
echo =====================================================
pause
