# 打包 HIDCircus 为便携版（onedir）
# 用法：powershell -ExecutionPolicy Bypass -File build.ps1
# 产物：dist\HIDCircus\HIDCircus.exe 以及 dist\HIDCircus-win-x64.zip
#
# 为什么不用 --onefile：单文件版启动时要把自己解压到 %TEMP%，
# 在受限环境（低权限/安全软件拦截/临时目录不可写）会直接报
#   "Could not create temporary directory!"
# 目录版没有这个解压步骤，启动更快，也不需要 %TEMP% 可写。
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.venv')) {
    Write-Host '创建虚拟环境（需要 Python 3.10）...'
    py -3.10 -m venv .venv
}

Write-Host '检查依赖...'
.\.venv\Scripts\python.exe -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '安装打包工具（首次需要联网）...'
    .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt pyinstaller
}

Write-Host '打包中（onedir）...'
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onedir --windowed `
    --name HIDCircus `
    --add-data "web;web" `
    --add-data "assets;assets" `
    --icon "assets\icon.ico" `
    app.py

$exe = 'dist\HIDCircus\HIDCircus.exe'
if (-not (Test-Path $exe)) {
    Write-Host '打包失败，请查看上方输出'
    exit 1
}

# 开机自启脚本要一起分发（exe 内不包含 tools/）
New-Item -ItemType Directory -Force 'dist\HIDCircus\tools' | Out-Null
Copy-Item 'tools\setup.ps1' 'dist\HIDCircus\tools\setup.ps1' -Force
Copy-Item 'setup.bat' 'dist\HIDCircus\setup.bat' -Force

$zip = 'dist\HIDCircus-win-x64.zip'
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path 'dist\HIDCircus\*' -DestinationPath $zip -Force
Write-Host "完成: $exe"
Write-Host "便携包: $zip"
