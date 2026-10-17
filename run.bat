@echo off
rem Start HIDCircus (silent). If nothing comes up, show the log tail.
rem Log is UTF-8; switch the console to UTF-8 so Chinese shows correctly.
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto no_venv
start "" ".venv\Scripts\pythonw.exe" app.py
ping -n 6 127.0.0.1 >nul 2>&1
rem Ask the app itself which port it took (8777-8784 fallback),
rem don't trust .runtime\port.txt: it may be stale from a previous run.
powershell -NoProfile -Command "$ok=$false; 8777..8784 | ForEach-Object { try { $r = Invoke-WebRequest -UseBasicParsing -Uri (\"http://127.0.0.1:$_/api/status\") -TimeoutSec 2; if ($r.StatusCode -eq 200 -and $r.Content -match '\"port\"') { Write-Host \"PORT=$_\"; $ok=$true } } catch {} }; if (-not $ok) { exit 1 } else { exit 0 }" >"%TEMP%\hidcircus_port.txt" 2>nul
if not errorlevel 1 goto ok
echo.
echo [!] The panel did not respond on 8777-8784.
echo     Last lines of logs\app.log:
echo ------------------------------------------------
powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; if (Test-Path 'logs\app.log') { Get-Content 'logs\app.log' -Tail 14 -Encoding UTF8 } else { Write-Host '(no log yet)' }"
echo ------------------------------------------------
echo Common causes:
echo   1. Started from a restricted launcher (process gets low integrity).
echo      Use the desktop shortcut, or run setup.bat once.
echo   2. An older instance is still running - check Task Manager for pythonw.exe.
echo   3. An elevated Edge is holding the profile - close all msedge.exe and retry.
pause
exit /b 1

:ok
type "%TEMP%\hidcircus_port.txt"
del "%TEMP%\hidcircus_port.txt" >nul 2>&1
exit /b 0

:no_venv
echo [!] .venv not found. Run: py -3.10 -m venv .venv
pause
exit /b 1

