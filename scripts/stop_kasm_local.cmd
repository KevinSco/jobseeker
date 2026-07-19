@echo off
setlocal EnableExtensions
cd /d "%~dp0..\.."
docker compose -f docker\kasm-local\docker-compose.yml down
echo Stopped local Kasm Chrome containers.
exit /b 0
