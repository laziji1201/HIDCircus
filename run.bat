@echo off
rem Start HIDCircus. If the panel does not come up, show the log tail.
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" goto no_venv
if not exist "tools\wait_panel.ps1" goto no_tools

echo Starting HIDCircus ...
start "" ".venv\Scripts\pythonw.exe" app.py

rem Give it a few seconds to bind a port and answer /api/status
ping -n 6 127.0.0.1 >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File "tools\wait_panel.ps1"
if not errorlevel 1 goto ok

echo.
echo [!] The panel did not answer on 8777-8784.
echo     Last lines of logs\app.log:
echo ------------------------------------------------
powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; if (Test-Path 'logs\app.log') { Get-Content 'logs\app.log' -Tail 14 -Encoding UTF8 } else { Write-Host '(no log yet)' }"
echo ------------------------------------------------
echo Possible reasons:
echo   1. Process lost rights (low integrity) - starts but cannot open the panel.
echo      Fix: run setup.bat once and use the desktop shortcut.
echo   2. An older instance holds the port - end pythonw.exe in Task Manager.
echo   3. An elevated Edge holds the profile - close all msedge.exe and retry.
echo.
pause
exit /b 1

:ok
echo.
echo Done. The panel should be open now (or use the tray icon).
exit /b 0

:no_venv
echo [!] .venv not found. Create it first:  py -3.10 -m venv .venv
pause
exit /b 1

:no_tools
echo [!] tools\wait_panel.ps1 is missing - the project folder looks incomplete.
pause
exit /b 1

