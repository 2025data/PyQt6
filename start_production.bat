@echo off
REM IESViewerAudit.py Production Launcher
REM This script starts the IES Viewer Audit application

echo.
echo ========================================
echo    IES Viewer Audit - Production
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ and try again
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

REM Install/update dependencies
echo Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Check if config exists
if not exist "config.py" (
    if exist "config_template.py" (
        echo.
        echo WARNING: No config.py found!
        echo Please copy config_template.py to config.py and update with your credentials
        echo.
        echo Opening config template for reference...
        notepad config_template.py
        echo.
        echo After setting up config.py, run this script again.
        pause
        exit /b 1
    )
)

REM Start the application
echo.
echo Starting IES Viewer Audit...
echo Press Ctrl+C to stop the application
echo.
python IESViewerAudit.py

REM Handle exit
echo.
echo Application stopped.
pause