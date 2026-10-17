@echo off
rem HIDCircus 启动脚本
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 未找到虚拟环境，请先运行：
  echo   py -3.10 -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" app.py
