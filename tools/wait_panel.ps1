# 等面板起来，并报告 HIDCircus 进程自己的权限级别
# 输出：LEVELAPP=...  PORT=...
# 低权限（被降权）时即使服务起来了，托盘和面板窗口也不会出现。
# 失败退出 1
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$log = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\app.log'
$levelApp = '未知'
if (Test-Path $log) {
    $line = Get-Content $log -Encoding UTF8 -Tail 60 |
        Where-Object { $_ -match '进程完整性' } | Select-Object -Last 1
    if ($line -match '进程完整性[:：]\s*(.+)$') { $levelApp = $Matches[1].Trim() }
}
Write-Host "LEVELAPP=$levelApp"

for ($port = 8777; $port -le 8784; $port++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/api/status" -TimeoutSec 2
        if ($r.StatusCode -eq 200 -and $r.Content -match '"port"') {
            Write-Host "PORT=$port"
            exit 0
        }
    } catch {
        continue
    }
}
exit 1
