@echo off
REM Windows runner for Task Scheduler.
REM %~dp0 is this file's folder (the repo root), so the task works regardless of
REM "Start in" and .env is found there. Output is appended to battery.log.
cd /d "%~dp0"
".venv\Scripts\python.exe" check_battery.py >> battery.log 2>&1
