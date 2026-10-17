@echo off
rem Open the panel window for the running HIDCircus instance
cd /d "%~dp0"
set "PORT=8777"
if exist ".runtime\port.txt" set /p PORT=<".runtime\port.txt"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" goto fallback
start "" "%EDGE%" --app=http://127.0.0.1:%PORT% --user-data-dir="%~dp0.runtime\browser-profile" --no-first-run --no-default-browser-check --no-proxy-server --disable-sync --disable-session-crashed-bubble --window-size=1180,820
exit /b 0

:fallback
start "" http://127.0.0.1:%PORT%
exit /b 0
