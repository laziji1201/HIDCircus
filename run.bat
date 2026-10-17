@echo off
rem HIDCircus launcher (keep this file ASCII + CRLF, cmd.exe breaks otherwise)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto no_venv
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0

:no_venv
echo [!] Python venv not found.
echo     py -3.10 -m venv .venv
echo     .venv\Scripts\pip install -r requirements.txt
pause
exit /b 1
