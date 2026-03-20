@echo off
REM run.bat — Start RBIS on Windows (no Docker needed)
REM Requirements: Python 3.10+

setlocal
set PORT=8000
set SCRIPT_DIR=%~dp0
set BACKEND=%SCRIPT_DIR%backend

echo.
echo  RBIS — Retail Behavior Intelligence System
echo  ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed.
    echo  Download from https://python.org
    pause
    exit /b 1
)

REM Create virtualenv
if not exist "%SCRIPT_DIR%.venv" (
    echo  Creating virtual environment...
    python -m venv "%SCRIPT_DIR%.venv"
)
call "%SCRIPT_DIR%.venv\Scripts\activate.bat"

REM Install dependencies
echo  Installing dependencies...
pip install --quiet --upgrade pip
pip install --quiet -r "%BACKEND%\requirements.txt"

REM Create data dirs
if not exist "%SCRIPT_DIR%data\snapshots" mkdir "%SCRIPT_DIR%data\snapshots"
if not exist "%SCRIPT_DIR%data\clips"     mkdir "%SCRIPT_DIR%data\clips"
if not exist "%SCRIPT_DIR%data\reports"  mkdir "%SCRIPT_DIR%data\reports"

echo.
echo  ==========================================
echo   Dashboard: http://localhost:%PORT%
echo.
echo   For phone access, find your IP address:
echo   Settings > WiFi > your network > IP address
echo   Then open: http://^<your-ip^>:%PORT%
echo  ==========================================
echo.

REM Start backend
cd "%BACKEND%"
set DATABASE_URL=sqlite+aiosqlite:///%SCRIPT_DIR%data/rbis.db
set LOCAL_STORAGE_PATH=%SCRIPT_DIR%data
set PORT=%PORT%
uvicorn app.main:app --host 0.0.0.0 --port %PORT%

pause
