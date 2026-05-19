@echo off
REM Algorithm Validation Platform - Quick Start Script
REM This script installs dependencies and launches the application

echo ========================================
echo   Algorithm Validation Platform v1.0
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.7 or higher from https://www.python.org/
    pause
    exit /b 1
)

echo [OK] Python detected
python --version
echo.

REM Install dependencies
echo [INFO] Installing required packages...
echo This may take a few minutes...
echo.

pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies
    echo Please check your internet connection and try again
    pause
    exit /b 1
)

echo.
echo [OK] All dependencies installed successfully
echo.
echo Starting Algorithm Validation Platform...
echo.

REM Launch the application
python algorithm_platform.py

if errorlevel 1 (
    echo.
    echo [ERROR] Application failed to start
    echo Please check the error messages above
    pause
)
