@echo off
rem 调试入口：有控制台窗口，能看到错误输出
cd /d "%~dp0"
".venv\Scripts\python.exe" -u app.py
pause
