@echo off
setlocal

cd /d "%~dp0"
title ReactXtract Server

echo.
echo ========================================
echo ReactXtract - Local development server
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: The .venv environment was not found.
    echo Run setup.cmd first.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo ERROR: The .env configuration file was not found.
    echo Run setup.cmd, then configure the OpenAI or Azure OpenAI credentials.
    echo.
    pause
    exit /b 1
)

echo [1/3] Applying database migrations...
".venv\Scripts\python.exe" "server\manage.py" migrate
if errorlevel 1 goto startup_failed

echo [2/3] Checking the Django application...
".venv\Scripts\python.exe" "server\manage.py" check
if errorlevel 1 goto startup_failed

echo [3/3] Starting ReactXtract...
echo.
echo Open http://127.0.0.1:8000/ in a browser.
echo Press Ctrl+C in this window to stop the server.
echo.
".venv\Scripts\python.exe" "server\manage.py" runserver 127.0.0.1:8000
exit /b %errorlevel%

:startup_failed
echo.
echo ERROR: ReactXtract could not start. Review the error messages above.
pause
exit /b 1
