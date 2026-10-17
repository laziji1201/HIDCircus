@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
rem Normal rights are enough for HIDCircus. If the scheduled task cannot be
rem created because this session is restricted, run this once as administrator.
if /i "%~1"=="uninstall" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Mode uninstall
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Mode install
)
echo.
pause
