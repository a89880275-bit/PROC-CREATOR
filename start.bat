@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto check
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -m venv .venv
if not errorlevel 1 goto install
:python
python -m venv .venv
if errorlevel 1 (
 echo Python 3.11+ is required. Install Python and enable Add Python to PATH.
 pause
 exit /b 1
)
:check
.venv\Scripts\python.exe -c "import fastapi, uvicorn, jinja2, openpyxl" >nul 2>nul
if not errorlevel 1 goto run
:install
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
 pause
 exit /b 1
)
:run
 echo Open http://127.0.0.1:8765 in your browser. Press Ctrl+C to stop.
.venv\Scripts\python.exe run.py
if errorlevel 1 pause
