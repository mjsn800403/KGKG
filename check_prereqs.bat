@echo off
setlocal
REM ============================================================
REM  KGtechvault — check & install prerequisites only.
REM  Run this once (or whenever you add a new dependency).
REM  Safe to re-run: every package is checked first and only
REM  installed if it's actually missing.
REM ============================================================
cd /d "%~dp0"

echo(
echo ===== Checking system tools =====

set "PY=py"
where py >nul 2>nul || set "PY=python"
where %PY% >nul 2>nul
if errorlevel 1 (
    echo [X] Python is not installed.
    echo     Install it from https://www.python.org/downloads/
    echo     ^(tick "Add Python to PATH"^), then run this again.
    pause
    exit /b 1
)
echo [OK] Python found.

where npm >nul 2>nul
if errorlevel 1 (
    echo [X] Node.js / npm is not installed.
    echo     Install the LTS version from https://nodejs.org/ then run this again.
    pause
    exit /b 1
)
echo [OK] Node.js found.

REM ===== Backend virtual environment =====
REM Recreate if it's missing, OR if it exists but was made WITHOUT
REM --system-site-packages (so it can't see your already-installed packages).
set "NEED_NEW_VENV=0"
if not exist "KG_backend\.venv\Scripts\python.exe" set "NEED_NEW_VENV=1"
if exist "KG_backend\.venv\pyvenv.cfg" (
    findstr /i /c:"include-system-site-packages = true" "KG_backend\.venv\pyvenv.cfg" >nul
    if errorlevel 1 set "NEED_NEW_VENV=1"
)
if "%NEED_NEW_VENV%"=="1" (
    echo(
    echo ===== Creating backend virtual environment =====
    if exist "KG_backend\.venv" rmdir /s /q "KG_backend\.venv"
    %PY% -m venv --system-site-packages "KG_backend\.venv"
) else (
    echo [OK] Backend virtual environment already exists.
)
set "VENV_PY=KG_backend\.venv\Scripts\python.exe"

REM ===== Backend Python packages (checked one by one, only missing get installed) =====
echo(
echo ===== Checking backend Python packages =====
for /f "usebackq tokens=1 delims==<>, " %%P in ("KG_backend\requirements.txt") do (
    if not "%%P"=="" (
        "%VENV_PY%" -m pip show %%P >nul 2>nul
        if errorlevel 1 (
            echo   installing %%P ...
            "%VENV_PY%" -m pip install %%P
        ) else (
            echo   [OK] %%P already installed
        )
    )
)

REM ===== Backend database migrations =====
echo(
echo ===== Applying backend migrations =====
pushd KG_backend
".venv\Scripts\python.exe" manage.py migrate
popd

REM ===== Frontend packages =====
echo(
echo ===== Checking frontend packages =====
if not exist "kg_frontend\node_modules" (
    echo   installing frontend packages, this may take a few minutes ...
    pushd kg_frontend
    call npm install
    popd
) else (
    echo [OK] Frontend packages already installed.
    echo      ^(run "npm install" inside kg_frontend manually if you changed package.json^)
)

echo(
echo ===== All prerequisites are ready. =====
echo You can now run start_all.bat
pause
endlocal
