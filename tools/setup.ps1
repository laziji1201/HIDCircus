# HIDCircus 开机自启 / 桌面快捷方式（只需运行一次）
# 用法：setup.bat            安装（开机自启 + 桌面快捷方式）
#       setup.bat uninstall  卸载
param([string]$Mode = "install", [switch]$Highest)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
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

# 源码运行用 pythonw，打包后用 exe（按可能性依次找）
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$exe = $null
foreach ($candidate in @((Join-Path $root 'HIDCircus.exe'), (Join-Path $root 'dist\HIDCircus.exe'))) {
    if (Test-Path $candidate) { $exe = $candidate; break }
}

if ($exe) {
    $launchExe = $exe
    $launchArgs = '--silent'
    $workDir = Split-Path -Parent $exe
} elseif (Test-Path $pythonw) {
    $launchExe = $pythonw
    $launchArgs = '"' + (Join-Path $root 'app.py') + '" --silent'
    $workDir = $root
} else {
    Write-Host '[!] 既没找到 HIDCircus.exe，也没找到 .venv\Scripts\pythonw.exe'
    Write-Host '    源码运行请先执行：py -3.10 -m venv .venv'
    exit 1
}

Write-Host "启动方式: $launchExe"

try {
    $action = New-ScheduledTaskAction -Execute $launchExe -Argument $launchArgs -WorkingDirectory $workDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'HIDCircus 外设控制台（托盘常驻）' -Force | Out-Null
    Write-Host '[OK] 已注册开机自启：登录 Windows 后自动进托盘'
} catch {
    Write-Host "[!] 注册开机自启失败：$($_.Exception.Message)"
    Write-Host '    常见原因：计划任务被组策略禁用，或当前会话权限被降级。'
    Write-Host '    可以手动把快捷方式放进 shell:startup 文件夹代替。'
    exit 2
}

try {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($shortcut)
    $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\schtasks.exe'
    $lnk.Arguments = '/run /tn "' + $taskName + '"'
    $lnk.WorkingDirectory = $workDir
    $lnk.Description = 'HIDCircus 外设控制台'
    $icon = Join-Path $root 'assets\icon.ico'
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Save()
    Write-Host "[OK] 已创建桌面快捷方式：$shortcut"
} catch {
    Write-Host "[!] 创建快捷方式失败：$($_.Exception.Message)"
}

Write-Host ''
Write-Host '以后双击桌面上的 HIDCircus 即可，它以正常权限启动，不会再要求提权。'
