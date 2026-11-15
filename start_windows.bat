@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto :error
if not exist ".env" copy ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof
:error
echo Setup failed. Read the error above and check Python 3.12 is installed.
pause
exit /b 1
