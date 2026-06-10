# 启动 manhua-workflow 开发服务器
# 用法: powershell -ExecutionPolicy Bypass -File start.ps1

$PORT = 8002

# 用 Get-NetTCPConnection 精确获取占用端口的 PID，比 netstat 解析可靠
$connections = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
if ($connections) {
    $owningPids = $connections.OwningProcess | Sort-Object -Unique
    foreach ($p in $owningPids) {
        if ($p -gt 0) {
            Write-Host "释放端口 $PORT (PID $p)"
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep 1
    # 确认端口已释放
    $remaining = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
    if ($remaining) {
        Write-Host "警告：端口 $PORT 仍被占用，可能需要手动处理"
    }
}

# 清理 Python 字节码缓存，确保加载最新代码
Get-ChildItem -Path $PSScriptRoot -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 启动服务器
Write-Host "启动服务器 http://localhost:$PORT"
Set-Location $PSScriptRoot
python main.py
