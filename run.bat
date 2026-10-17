@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto no_venv
if not exist "tools\wait_panel.ps1" goto no_tools

echo Starting HIDCircus ...
start "" ".venv\Scripts\pythonw.exe" app.py
ping -n 6 127.0.0.1 >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File "tools\wait_panel.ps1"
set RC=%ERRORLEVEL%

rem Low integrity: service starts but Windows blocks tray icon and window
powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $l = Get-Content 'logs\app.log' -Encoding UTF8 -Tail 60 -ErrorAction SilentlyContinue | Select-String '\u8fdb\u7a0b\u5b8c\u6574\u6027' | Select-Object -Last 1; if ($l -and $l.Line -match '\u4f4e') { exit 9 }"
if errorlevel 9 goto low_rights

if not "%RC%"=="0" goto failed
echo.
echo Done. Panel should be open (or check the tray icon).
timeout /t 3 >nul 2>&1
exit /b 0

:low_rights
echo.
echo [!] HIDCircus runs with LOW rights in this session.
echo     Service is up, but Windows blocks the tray icon and the window.
echo     This is an environment issue, not a bug.
echo.
echo     Fix - pick one:
echo       1. Use the HIDCircus shortcut on your Desktop (run setup.bat once)
echo       2. Open the panel manually: http://127.0.0.1:8777
echo.
echo     Or relaunch elevated right now (one UAC prompt, then it works):
choice /c YN /n /m "Relaunch as administrator? [Y/N] "
if errorlevel 2 goto low_stay
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 2

:low_stay
pause
exit /b 2

:failed
echo.
echo [!] Panel did not answer on 8777-8784.
echo     Last lines of logs\app.log:
echo ------------------------------------------------
powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; if (Test-Path 'logs\app.log') { Get-Content 'logs\app.log' -Tail 14 -Encoding UTF8 } else { Write-Host '(no log yet)' }"
echo ------------------------------------------------
echo   1. An older instance may hold the port - end pythonw.exe in Task Manager.
echo   2. An elevated Edge may hold the browser profile - close msedge.exe, retry.
echo   3. Missing deps: .venv\Scripts\pip install -r requirements.txt
echo.
pause
exit /b 1

:no_venv
echo [!] .venv not found. Create it first:  py -3.10 -m venv .venv
pause
exit /b 1

:no_tools
echo [!] tools\wait_panel.ps1 is missing - the project folder looks incomplete.
pause
exit /b 1

