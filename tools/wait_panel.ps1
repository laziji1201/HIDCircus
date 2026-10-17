# 等面板起来：扫描 8777-8784，成功则打印 PORT=xxxx 并退出 0
# 失败退出 1（run.bat 据此打印日志尾部）
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

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
