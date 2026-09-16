# 造价数据库 FastAPI 本地启动脚本
# 用法: 在 PowerShell 里 .\start_dev.ps1
# 作用: 自动检查 PostgreSQL 5432 端口 -> 没通则拉起 -> 等 ready -> 启动 uvicorn

$ErrorActionPreference = "Continue"
$PY = "C:\Users\ht835\AppData\Local\Programs\Python\Python312\python.exe"
$PG_CTL = "E:\PostgreSQL\pgsql\bin\pg_ctl.exe"
$PG_DATA = "E:\PostgreSQL\data"
$PORT = 8777
$DB_PORT = 5432

# 1. 检查 PG 是否已在跑（探 5432 端口）
$pgRunning = Test-NetConnection -ComputerName 127.0.0.1 -Port $DB_PORT -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $pgRunning) {
    Write-Host "[start_dev] PostgreSQL 未运行，正在启动..." -ForegroundColor Yellow
    & $PG_CTL -D $PG_DATA -l "E:\PostgreSQL\data\pg_startup.log" start
    # 等 PG ready（最多 15 秒）
    for ($i=0; $i -lt 15; $i++) {
        Start-Sleep 1
        $ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $DB_PORT -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($ok) { break }
    }
    $pgRunning = Test-NetConnection -ComputerName 127.0.0.1 -Port $DB_PORT -InformationLevel Quiet -WarningAction SilentlyContinue
}
if (-not $pgRunning) {
    Write-Host "[start_dev] PostgreSQL 启动失败！查看 E:\PostgreSQL\data\pg_startup.log" -ForegroundColor Red
    exit 1
}
Write-Host "[start_dev] PostgreSQL 已就绪 (port $DB_PORT)" -ForegroundColor Green

# 2. 杀掉旧 uvicorn 进程
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*uvicorn*app.main*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 1

# 3. 启动 uvicorn
Write-Host "[start_dev] 启动 uvicorn on http://127.0.0.1:$PORT" -ForegroundColor Cyan
Write-Host "[start_dev] 开发期登录: http://127.0.0.1:$PORT/login?token=zaojia-dev-token-2026&next=/admin/dashboard" -ForegroundColor Gray
& $PY -m uvicorn app.main:app --host 127.0.0.1 --port $PORT
