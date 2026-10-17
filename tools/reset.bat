@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."

rem Old instances may run elevated, so normal rights cannot stop them: elevate once.
net session >nul 2>&1
if not errorlevel 1 goto elevated
echo Requesting administrator rights (needed to stop an elevated instance) ...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:elevated
echo.
echo === Stopping HIDCircus instances (by port) ===
powershell -NoProfile -Command "foreach ($p in 8777..8784) { $c = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue; if ($c) { Write-Host ('  stop pid ' + $c.OwningProcess + ' on port ' + $p); Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } }"

echo === Stopping HIDCircus processes ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='HIDCircus.exe'\" | Where-Object { $_.CommandLine -match 'app\.py' -or $_.Name -eq 'HIDCircus.exe' } | ForEach-Object { Write-Host ('  stop ' + $_.Name + ' ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo === Stopping Edge processes that use our profile ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -match 'HIDCircus' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo === Removing stale browser profiles ===
if exist ".runtime\browser-profile" rmdir /s /q ".runtime\browser-profile"
for /d %%d in (".runtime\browser-profile-*") do rmdir /s /q "%%d"

echo.
echo Remaining listeners on 8777-8784:
powershell -NoProfile -Command "$n = 0; foreach ($p in 8777..8784) { $c = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue; if ($c) { $n++; Write-Host ('  port ' + $p + ' still held by pid ' + $c.OwningProcess) } }; if ($n -eq 0) { Write-Host '  none' }"
echo.
echo Done. Start HIDCircus again (desktop shortcut).
echo.
pause
