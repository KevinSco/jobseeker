@echo off
cd /d "%~dp0.."
python -m job_automation.main run
exit /b %ERRORLEVEL%
