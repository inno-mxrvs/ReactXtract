@echo off
setlocal

cd /d "%~dp0"
title ReactXtract Setup

echo.
echo ========================================
echo ReactXtract - First-time setup
echo ========================================
echo.

if exist ".venv\Scripts\python.exe" goto install_requirements

echo [1/3] Creating the Python virtual environment...
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv ".venv"
) else (
    where python >nul 2>&1
    if errorlevel 1 goto python_missing
    python -m venv ".venv"
)

if not exist ".venv\Scripts\python.exe" goto venv_failed

:install_requirements
echo [2/3] Installing Python requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_failed

".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto install_failed

echo [3/3] Preparing the local environment file...
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo Created .env from .env.example.
        echo Replace it with the approved .env file sent through Teams.
    ) else (
        echo WARNING: .env.example was not found. Create .env manually.
    )
) else (
    echo Existing .env was preserved.
)

echo.
echo ========================================
echo Setup completed successfully.
echo Paste the approved .env file from Teams into this folder.
echo Run runserver.cmd to start ReactXtract.
echo ========================================
echo.
pause
exit /b 0

:python_missing
echo.
echo ERROR: Python was not found.
echo Install 64-bit Python 3.12 or 3.13 and enable "Add Python to PATH".
goto failed

:venv_failed
echo.
echo ERROR: The .venv virtual environment could not be created.
goto failed

:install_failed
echo.
echo ERROR: Python requirements could not be installed.
echo Check the internet connection and the error messages above.

:failed
echo.
echo Setup did not complete.
pause
exit /b 1
