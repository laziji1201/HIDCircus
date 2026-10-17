@echo off
rem Reset HIDCircus state: stop every instance and every browser it spawned.
rem Use this when panels stop opening or Edge keeps asking about elevated instances.
rem
rem Usage:  tools\reset.bat
chcp 65001 >nul 2>&1
cd /d "%~dp0.."

echo.
echo === Stopping HIDCircus instances ===
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq HIDCircus*" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'app\.py' } | ForEach-Object { Write-Host ('  stop pythonw ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo === Stopping Edge processes that use our profile ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -match 'HIDCircus' } | ForEach-Object { Write-Host ('  stop msedge ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo === Removing stale browser profiles ===
if exist ".runtime\browser-profile" rmdir /s /q ".runtime\browser-profile"
if exist ".runtime\edge-profile" rmdir /s /q ".runtime\edge-profile"
for /d %%d in (".runtime\browser-profile-*") do rmdir /s /q "%%d"

echo.
echo Done. Now start HIDCircus again (desktop shortcut or run.bat).
echo.
pause
