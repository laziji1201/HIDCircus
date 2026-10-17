@echo off
rem One-time setup: autostart at logon + desktop shortcut (normal rights, no UAC)
cd /d "%~dp0"
if /i "%~1"=="uninstall" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Mode uninstall
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Mode install
)
echo.
pause
