@echo off
cd /d "%~dp0"
call npm run dev
echo(
echo Frontend stopped. Press any key to close this window.
pause >nul
