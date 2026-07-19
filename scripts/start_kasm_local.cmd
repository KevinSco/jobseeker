@echo off
setlocal EnableExtensions
cd /d "%~dp0..\.."

echo Starting Docker Desktop if needed...
where docker >nul 2>&1
if errorlevel 1 (
  echo Docker is not installed. Install Docker Desktop first.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker engine is not running. Launching Docker Desktop...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  echo Waiting for Docker engine...
  set /a _tries=0
  :wait_docker
  timeout /t 3 /nobreak >nul
  docker info >nul 2>&1
  if not errorlevel 1 goto docker_ready
  set /a _tries+=1
  if %_tries% geq 40 (
    echo Timed out waiting for Docker. Open Docker Desktop manually, then re-run this script.
    exit /b 1
  )
  goto wait_docker
)

:docker_ready
echo Pulling / starting Chrome-only containers (not a full desktop)...
docker compose -f docker\kasm-local\docker-compose.yml up -d
if errorlevel 1 (
  echo Failed to start Chrome containers.
  exit /b 1
)

echo.
echo Waiting for CDP ports...
timeout /t 12 /nobreak >nul

echo.
echo Local Chrome browsers are up:
echo   Watch browser 1:  https://127.0.0.1:6911  (no Kasm password — gate via JobSeek sign-in)
echo   Watch browser 2:  https://127.0.0.1:6912  (no Kasm password — gate via JobSeek sign-in)
echo   CDP browser 1:    http://127.0.0.1:9333
echo   CDP browser 2:    http://127.0.0.1:9334
echo.
echo Accept the self-signed cert warning once for Watch embeds.
echo Then set KASM_ENABLED=true in .env and restart the JobSeek dashboard.
echo Find Jobs / Watch require a JobSeek account; browsing jobs stays free.
exit /b 0
