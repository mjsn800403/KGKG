@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" manage.py runserver
echo(
echo Backend stopped. Press any key to close this window.
pause >nul
