"""
造价数据门户（FastAPI 版）一键本地调试启动脚本

功能：
1. 自动检查 PostgreSQL 是否运行
2. 若未启动，自动启动 PG 并等待就绪
3. 启动 uvicorn 本地调试服务（端口 8777，--reload）

用法：
    python scripts/start_dev.py

停止服务：
    Ctrl+C 停止 uvicorn；PG 保持运行（下次启动更快）
    如需停止 PG：E:\\PostgreSQL\\pgsql\\bin\\pg_ctl.exe stop -D "E:\\PostgreSQL\\data"
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# ============================================================
# 配置（根据实际环境修改）
# ============================================================

# PostgreSQL 配置
PG_CTL = r"E:\PostgreSQL\pgsql\bin\pg_ctl.exe"
PG_DATA = r"E:\PostgreSQL\data"
PG_LOG = os.path.join(PG_DATA, "pg.log")
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "odoo"
PG_DBNAME = "zaojia_fastapi"
PG_WAIT_TIMEOUT = 30  # 等待 PG 就绪的最大秒数

# uvicorn 配置
UVICORN_HOST = "127.0.0.1"
UVICORN_PORT = 8777
APP_MODULE = "app.main:app"

# 项目根目录（脚本所在目录的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ============================================================
# PostgreSQL 管理
# ============================================================

def check_pg_running() -> bool:
    """检查 PostgreSQL 是否运行（尝试连接数据库）"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            dbname=PG_DBNAME,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


def start_postgres() -> bool:
    """启动 PostgreSQL，等待就绪，返回是否成功"""
    print("[1/3] 检查 PostgreSQL...")

    if check_pg_running():
        print("      ✅ PostgreSQL 已在运行")
        return True

    print(f"      ⚠️  PostgreSQL 未启动，正在启动...")
    print(f"      数据目录: {PG_DATA}")

    # 检查 pg_ctl 是否存在
    if not os.path.exists(PG_CTL):
        print(f"      ❌ pg_ctl 不存在: {PG_CTL}")
        print("      请修改脚本中的 PG_CTL 路径")
        return False

    # 启动 PG
    try:
        result = subprocess.run(
            [PG_CTL, "start", "-D", PG_DATA, "-l", PG_LOG],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # pg_ctl start 即使已在运行也会返回 0，所以不严格检查返回码
        if "server started" in result.stdout or "another server might be running" in result.stdout:
            pass  # 继续等待就绪
        elif result.returncode != 0:
            print(f"      ❌ pg_ctl 启动失败:")
            print(f"      stdout: {result.stdout}")
            print(f"      stderr: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("      ⚠️  pg_ctl 启动超时，继续等待 PG 就绪...")
    except Exception as e:
        print(f"      ❌ 启动 PG 时出错: {e}")
        return False

    # 轮询等待 PG 就绪
    print(f"      等待 PostgreSQL 就绪（最多 {PG_WAIT_TIMEOUT} 秒）...")
    for i in range(PG_WAIT_TIMEOUT):
        time.sleep(1)
        if check_pg_running():
            print(f"      ✅ PostgreSQL 已就绪（等待 {i + 1} 秒）")
            return True
        if (i + 1) % 5 == 0:
            print(f"      ...已等待 {i + 1} 秒")

    print(f"      ❌ PostgreSQL 在 {PG_WAIT_TIMEOUT} 秒内未就绪")
    print(f"      请检查日志: {PG_LOG}")
    return False


# ============================================================
# 数据库数据量检查
# ============================================================

def check_db_data() -> None:
    """检查数据库数据量并打印"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, user=PG_USER, dbname=PG_DBNAME
        )
        cur = conn.cursor()
        tables = ["boq_item", "import_batch", "material_dict", "audit_log", "cost_catalog"]
        print("      数据库数据量:")
        for table in tables:
            try:
                cur.execute(f"SELECT count(*) FROM {table}")
                count = cur.fetchone()[0]
                print(f"        {table}: {count:,} 条")
            except Exception:
                pass  # 表不存在时跳过
        conn.close()
    except Exception as e:
        print(f"      ⚠️  检查数据量失败: {e}")


# ============================================================
# uvicorn 启动
# ============================================================

def start_uvicorn() -> None:
    """启动 uvicorn 本地调试服务（前台运行，Ctrl+C 停止）"""
    print("\n[2/3] 启动 uvicorn 本地调试服务...")
    print(f"      地址: http://{UVICORN_HOST}:{UVICORN_PORT}")
    print(f"      模块: {APP_MODULE}")
    print(f"      模式: --reload（代码修改自动重载）")
    print()

    # 切换到项目根目录
    os.chdir(PROJECT_ROOT)

    # 构建 uvicorn 命令
    cmd = [
        sys.executable, "-m", "uvicorn", APP_MODULE,
        "--host", UVICORN_HOST,
        "--port", str(UVICORN_PORT),
        "--reload",
    ]

    print("[3/3] 服务运行中，按 Ctrl+C 停止")
    print("=" * 60)
    print()
    print("  Admin 管理端（需登录）:")
    print(f"    http://{UVICORN_HOST}:{UVICORN_PORT}/login?token=zaojia-dev-token-2026&role=admin&next=/admin/dashboard")
    print()
    print("  Portal 门户端（可选登录）:")
    print(f"    http://{UVICORN_HOST}:{UVICORN_PORT}/portal/dashboard")
    print()
    print("=" * 60)
    print()

    # 前台运行 uvicorn（阻塞，直到 Ctrl+C）
    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT)
    except KeyboardInterrupt:
        print("\n\n收到停止信号，正在关闭 uvicorn...")
    print("\nuvicorn 已停止。PostgreSQL 保持运行（下次启动更快）。")


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("  造价数据门户（FastAPI 版）- 本地调试一键启动")
    print("=" * 60)
    print()

    # 步骤 1: 启动 PostgreSQL
    if not start_postgres():
        print("\n❌ PostgreSQL 启动失败，无法继续。")
        print("   请手动检查 PG 配置后重试。")
        sys.exit(1)

    # 检查数据库数据量
    check_db_data()

    # 步骤 2 & 3: 启动 uvicorn
    start_uvicorn()


if __name__ == "__main__":
    main()
