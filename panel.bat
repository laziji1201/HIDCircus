@echo off
rem 只打开面板窗口；后台服务由 app.py 负责，窗口关了服务还在
cd /d "%~dp0"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%EDGE%" (
    start "" "%EDGE%" --app=http://127.0.0.1:8777 --user-data-dir="%~dp0.runtime\edge-profile" --no-first-run --no-default-browser-check --disable-session-crashed-bubble --window-size=1180,820
) else (
    start "" http://127.0.0.1:8777
)
