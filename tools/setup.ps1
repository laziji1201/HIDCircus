# HIDCircus 开机自启 / 桌面快捷方式配置（只需运行一次）
# 用法：setup.bat            安装（开机自启 + 桌面快捷方式）
#       setup.bat uninstall  卸载
param([string]$Mode = "install")

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$appPy = Join-Path $root 'app.py'
$icon = Join-Path $root 'assets\icon.ico'
$taskName = 'HIDCircus'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop 'HIDCircus.lnk'

function Remove-Everything {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $shortcut -ErrorAction SilentlyContinue
    Write-Host '[OK] 已取消开机自启并删除桌面快捷方式'
}

if ($Mode -eq 'uninstall') {
    Remove-Everything
    exit 0
}

if (-not (Test-Path $pythonw)) {
    Write-Host "[!] 找不到 .venv\Scripts\pythonw.exe"
    Write-Host "    请先在项目目录运行：py -3.10 -m venv .venv"
    exit 1
}

# 1) 计划任务：登录时以当前用户身份启动，静默进托盘
#    不用 -RunLevel Highest：那样每次都要管理员权限；普通权限就够（托盘/窗口都正常）
$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument ('"' + $appPy + '" --silent') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'HIDCircus 外设控制台（托盘常驻）' -Force | Out-Null
Write-Host '[OK] 已注册开机自启：登录 Windows 后自动进托盘'

# 2) 桌面快捷方式：走计划任务启动，避免从低权限入口继承降权
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($shortcut)
$lnk.TargetPath = Join-Path $env:SystemRoot 'System32\schtasks.exe'
$lnk.Arguments = "/run /tn `"$taskName`""
$lnk.WorkingDirectory = $root
$lnk.IconLocation = $icon
$lnk.Description = 'HIDCircus 外设控制台'
$lnk.Save()
Write-Host "[OK] 已创建桌面快捷方式：$shortcut"
Write-Host ''
Write-Host '以后双击桌面上的 HIDCircus 即可，它以正常权限启动，不会再要求提权。'
