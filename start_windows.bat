@echo off
cd /d "%~dp0"
if not exist ".env" (
  echo Run python scripts\configure.py once to create local settings.
  pause
  exit /b 1
)
docker compose up --build -d --wait
pause
