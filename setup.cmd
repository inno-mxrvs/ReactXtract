@echo off
setlocal

cd /d "%~dp0"
title ReactXtract Setup

echo.
echo ========================================
echo ReactXtract - First-time setup
echo ========================================
echo.

if exist ".venv\Scripts\python.exe" goto validate_existing_venv

echo [1/3] Creating the Python virtual environment...
where py >nul 2>&1
if errorlevel 1 goto try_python_command

py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and getattr(sys, '_is_gil_enabled', lambda: True)() else 1)" >nul 2>&1
if not errorlevel 1 goto create_with_python_313

py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) and getattr(sys, '_is_gil_enabled', lambda: True)() else 1)" >nul 2>&1
if not errorlevel 1 goto create_with_python_312

goto python_missing

:try_python_command
where python >nul 2>&1
if errorlevel 1 goto python_missing
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 12), (3, 13)) and getattr(sys, '_is_gil_enabled', lambda: True)() else 1)" >nul 2>&1
if errorlevel 1 goto python_missing
python -m venv ".venv"
goto venv_created

:create_with_python_313
echo Using standard Python 3.13.
py -3.13 -m venv ".venv"
goto venv_created

:create_with_python_312
echo Using standard Python 3.12.
py -3.12 -m venv ".venv"

:venv_created

if not exist ".venv\Scripts\python.exe" goto venv_failed
goto install_requirements

:validate_existing_venv
echo [1/3] Checking the existing virtual environment...
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 12), (3, 13)) and getattr(sys, '_is_gil_enabled', lambda: True)() else 1)" >nul 2>&1
if errorlevel 1 goto incompatible_venv
echo Existing .venv uses a supported standard Python runtime.

:install_requirements
echo [2/3] Installing Python requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_failed

".venv\Scripts\python.exe" -m pip install --only-binary=PyMuPDF -r "requirements.txt"
if errorlevel 1 goto install_failed

".venv\Scripts\python.exe" -c "import pymupdf; print('PyMuPDF installed:', pymupdf.version)"
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
echo ERROR: A supported standard Python runtime was not found.
echo Install 64-bit standard Python 3.13 or 3.12 from python.org.
echo Enable "Add Python to PATH" and the Python Launcher during installation.
echo Do not install or select the free-threaded Python build.
echo.
echo Installed runtimes detected by the Python Launcher:
py -0p 2>nul
goto failed

:incompatible_venv
echo.
echo ERROR: The existing .venv was created with an unsupported Python runtime.
echo ReactXtract requires standard 64-bit Python 3.13 or 3.12.
echo Python 3.15 free-threaded environments are not supported.
echo.
echo Delete the .venv folder, install a supported Python version, and run setup.cmd again.
echo PowerShell command: Remove-Item -Recurse -Force .venv
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
