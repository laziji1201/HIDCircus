@echo off
rem Debug launcher: keeps a console so errors are visible
rem Set HIDCIRCUS_DEBUG=1 to also log every HTTP request to logs\requests.log
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto no_venv
".venv\Scripts\python.exe" -u app.py
pause
exit /b 0

:no_venv
echo [!] Python venv not found. See README.
pause
exit /b 1
