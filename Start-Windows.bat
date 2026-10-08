@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python app.py
pause
exit /b
:failed
 echo Install Python 3.11 or 3.12 from python.org and try again.
 pause
