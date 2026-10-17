# 打包 HIDCircus 为单文件 exe
# 用法：powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.venv')) {
    Write-Host '创建虚拟环境（需要 Python 3.10，pywebview 的 pythonnet 尚不支持 3.13）...'
    py -3.10 -m venv .venv
}

Write-Host '安装依赖...'
.\.venv\Scripts\pip.exe install --quiet -r requirements.txt pyinstaller

Write-Host '打包中...'
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed `
    --name HIDCircus `
    --add-data "web;web" `
    --add-data "assets;assets" `
    --icon "assets\icon.ico" `
    app.py

if (Test-Path 'dist\HIDCircus.exe') {
    Write-Host "完成: dist\HIDCircus.exe"
} else {
    Write-Host '打包失败，请查看上方输出'
    exit 1
}
