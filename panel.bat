@echo off
rem Open the panel window only (service is provided by app.py)
cd /d "%~dp0"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" goto fallback
start "" "%EDGE%" --app=http://127.0.0.1:8777 --user-data-dir="%~dp0.runtime\edge-profile" --no-first-run --no-default-browser-check --disable-session-crashed-bubble --window-size=1180,820
exit /b 0

:fallback
start "" http://127.0.0.1:8777
exit /b 0
