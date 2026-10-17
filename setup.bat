@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
rem If not elevated, relaunch elevated once (single UAC prompt),
rem then register a HIGHEST-level task so future starts are silent.
net session >nul 2>&1
if not errorlevel 1 goto elevated

echo Requesting administrator rights once ...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:elevated
if /i "%~1"=="uninstall" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Mode uninstall
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Mode install -Highest
)
echo.
pause
