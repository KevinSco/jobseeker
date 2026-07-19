@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Keep Playwright browsers in the project so Cursor sandbox paths can't break launches.
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.playwright-browsers"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  echo Virtual environment not found. Creating .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv. Is Python installed?
    pause
    exit /b 1
  )
  set "PYTHON=.venv\Scripts\python.exe"
  echo Installing Python packages ...
  "%PYTHON%" -m pip install -e . -q
  if errorlevel 1 (
    echo Failed to install project dependencies.
    pause
    exit /b 1
  )
)

REM Ensure Playwright Chromium is installed (needed for Find Jobs / portal search).
"%PYTHON%" -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()" >nul 2>&1
if errorlevel 1 (
  echo Playwright browser not found. Installing Chromium now...
  echo This can take a few minutes the first time.
  echo.
  "%PYTHON%" -m playwright install chromium
  if errorlevel 1 (
    echo Failed to install Playwright Chromium.
    pause
    exit /b 1
  )
  echo Playwright Chromium installed.
  echo.
)

echo Starting JobSeek dashboard at http://127.0.0.1:8000
echo Press Ctrl+C to stop.
echo.

start "" "http://127.0.0.1:8000"
"%PYTHON%" -m job_automation.main dashboard --host 127.0.0.1 --port 8000
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo Dashboard exited with error code %EXITCODE%.
  pause
)

exit /b %EXITCODE%
