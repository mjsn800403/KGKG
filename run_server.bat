@echo off
setlocal
REM ============================================================
REM  KGtechvault — start backend + frontend.
REM  Assumes check_prereqs.bat has already been run once.
REM  Opens your browser to localhost:3000 once the site is ready.
REM ============================================================
cd /d "%~dp0"

if not exist "KG_backend\.venv\Scripts\python.exe" (
    echo [X] Backend is not set up yet.
    echo     Run check_prereqs.bat first.
    pause
    exit /b 1
)
if not exist "kg_frontend\node_modules" (
    echo [X] Frontend packages are not installed yet.
    echo     Run check_prereqs.bat first.
    pause
    exit /b 1
)

echo Starting servers ...
start "KG Backend"  "%~dp0KG_backend\_run_backend.bat"
start "KG Frontend" "%~dp0kg_frontend\_run_frontend.bat"

echo Waiting for the frontend to be ready...
:waitloop
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('localhost',3000);$c.Close();exit 0}catch{exit 1}" >nul 2>nul
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)

echo Frontend is up. Opening browser...
start "" http://localhost:3000

echo(
echo Both servers are running in their own windows.
echo Close those windows to stop the servers.
endlocal
