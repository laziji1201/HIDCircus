@echo off
rem Start HIDCircus (silent). If nothing comes up, show the log tail.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto no_venv
start "" ".venv\Scripts\pythonw.exe" app.py
timeout /t 4 /nobreak >nul
set "PORT="
if exist ".runtime\port.txt" set /p PORT=<".runtime\port.txt"
if not defined PORT set "PORT=8777"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:%PORT%/api/status') -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if not errorlevel 1 goto ok
echo.
echo [!] The panel did not respond on port %PORT%.
echo     Last lines of logs\app.log:
echo ------------------------------------------------
powershell -NoProfile -Command "if (Test-Path 'logs\app.log') { Get-Content 'logs\app.log' -Tail 12 } else { Write-Host '(no log yet)' }"
echo ------------------------------------------------
echo Common causes:
echo   1. It was started from a sandboxed/restricted launcher (process gets low integrity).
echo      Use the desktop shortcut or run setup.bat once.
echo   2. An older instance is still running; check Task Manager for pythonw.exe.
pause
exit /b 1

:ok
exit /b 0

:no_venv
echo [!] .venv not found. Run: py -3.10 -m venv .venv
pause
exit /b 1
