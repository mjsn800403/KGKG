@echo off
REM ============================================================
REM  Double-click to open the parser GUI.
REM  First run sets things up automatically (takes a minute).
REM  Every run after that is instant. Nothing to type.
REM ============================================================
cd /d "%~dp0"

REM --- find Python
set "PY=py"
where py >nul 2>nul || set "PY=python"

REM --- create a private environment once
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up for the first time, please wait...
    %PY% -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet beautifulsoup4 html5lib
)

REM --- launch the GUI with no console window
start "" ".venv\Scripts\pythonw.exe" parser_gui.py
