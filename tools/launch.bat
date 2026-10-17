@echo off
rem One-click launcher used by the desktop shortcut.
rem 1) Prefer the on-demand scheduled task (created by setup.bat) - it runs
rem    with the right rights and needs no UAC. 2) Otherwise start normally.
chcp 65001 >nul 2>&1
cd /d "%~dp0.."

schtasks /query /tn "HIDCircusPanel" >nul 2>&1
if errorlevel 1 goto direct
schtasks /run /tn "HIDCircusPanel" >nul 2>&1
if errorlevel 1 goto direct
exit /b 0

:direct
if exist ".venv\Scripts\pythonw.exe" goto py
if exist "HIDCircus.exe" goto exe
echo [!] Neither .venv nor HIDCircus.exe found.
pause
exit /b 1

:py
start "" ".venv\Scripts\pythonw.exe" app.py --panel
exit /b 0

:exe
start "" "HIDCircus.exe" --panel
exit /b 0
