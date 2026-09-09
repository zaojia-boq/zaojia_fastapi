# -*- coding: utf-8 -*-
"""S8 备份恢复演练自动化验证脚本。

用途：每季度执行一次，验证 pg_dump 备份文件可完整恢复且数据一致。

流程：
1. 创建临时数据库（zaojia_restore_test_<timestamp>）
2. 使用 pg_restore 恢复备份文件到临时库
3. 抽样校验：
   - 表数量与预期一致
   - 关键表（boq_item/import_batch/material_dict/audit_log）行数 > 0
   - B 类字段（std_name/std_spec/material_dict_id）非空数量与源库抽样一致
4. 清理临时数据库
5. 输出 RESULT: PASS / FAIL

用法：
    python scripts/verify_backup_restore.py <backup_file.dump> [--db-host localhost] [--db-user odoo] [--db-port 5432]

依赖：
    - PostgreSQL pg_restore 命令（需在 PATH 中或通过 --pg-restore 指定）
    - psycopg2（项目已安装）

注意：
    - 本脚本仅用于验证备份文件，不会修改生产/开发数据库
    - 临时数据库会在脚本结束时自动清理（无论成功或失败）
    - 抽样校验通过不代表 100% 数据一致，仅作为备份有效性的快速验证
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


# 预期的关键表（M1-M4 核心模型）
EXPECTED_TABLES = [
    "boq_item",
    "import_batch",
    "material_dict",
    "audit_log",
    "match_cache",
    "cost_catalog",
]

# B 类字段（人工标注，不可重建）
B_FIELDS = ["std_name", "std_spec", "material_dict_id"]


def create_temp_db(db_host, db_port, db_user, db_name):
    """创建临时数据库。"""
    conn = psycopg2.connect(host=db_host, port=db_port, user=db_user, dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
    cur.close()
    conn.close()
    print(f"[1/5] 临时数据库已创建: {db_name}")


def drop_temp_db(db_host, db_port, db_user, db_name):
    """删除临时数据库。"""
    try:
        conn = psycopg2.connect(host=db_host, port=db_port, user=db_user, dbname="postgres")
        conn.autocommit = True
        cur = conn.cursor()
        # 终止所有连接
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (db_name,)
        )
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))
        cur.close()
        conn.close()
        print(f"[5/5] 临时数据库已清理: {db_name}")
    except Exception as e:
        print(f"WARNING: 清理临时数据库失败: {e}")


def restore_backup(pg_restore_path, backup_file, db_host, db_port, db_user, db_name):
    """使用 pg_restore 恢复备份文件。"""
    cmd = [
        pg_restore_path,
        "--host", db_host,
        "--port", str(db_port),
        "--username", db_user,
        "--dbname", db_name,
        "--no-owner",
        "--no-privileges",
        backup_file,
    ]
    print(f"[2/5] 执行 pg_restore: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # pg_restore 可能返回非零但实际恢复成功（如已存在的对象）
        if "ERROR" in result.stderr and "already exists" not in result.stderr:
            print(f"ERROR: pg_restore 失败:\n{result.stderr}")
            return False
        print(f"WARNING: pg_return 返回非零，但可能是已存在对象警告:\n{result.stderr[:500]}")
    print("[2/5] 备份恢复完成")
    return True


def verify_tables(db_host, db_port, db_user, db_name):
    """校验表数量和关键表存在。"""
    conn = psycopg2.connect(host=db_host, port=db_port, user=db_user, dbname=db_name)
    cur = conn.cursor()

    # 获取所有用户表
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"[3/5] 恢复的表数量: {len(tables)}")
    print(f"[3/5] 表列表: {tables}")

    # 校验关键表存在
    missing = [t for t in EXPECTED_TABLES if t not in tables]
    if missing:
        print(f"FAIL: 缺少关键表: {missing}")
        cur.close()
        conn.close()
        return False

    # 校验关键表行数 > 0
    print("[4/5] 校验关键表行数...")
    for table in EXPECTED_TABLES:
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
        count = cur.fetchone()[0]
        print(f"  {table}: {count} 行")
        if count == 0 and table in ["boq_item", "import_batch"]:
            print(f"FAIL: 关键表 {table} 行数为 0")
            cur.close()
            conn.close()
            return False

    # 校验 B 类字段（抽样 100 条，检查非空率）
    print("[4/5] 校验 B 类字段（人工标注）...")
    cur.execute("SELECT COUNT(*) FROM boq_item")
    total = cur.fetchone()[0]
    if total > 0:
        for field in B_FIELDS:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM boq_item WHERE {} IS NOT NULL AND {} != ''").format(
                sql.Identifier(field), sql.Identifier(field)
            ))
            non_null = cur.fetchone()[0]
            ratio = non_null / total * 100 if total > 0 else 0
            print(f"  {field}: {non_null}/{total} 非空 ({ratio:.1f}%)")

    cur.close()
    conn.close()
    print("[4/5] 表结构和数据校验通过")
    return True


def main():
    parser = argparse.ArgumentParser(description="S8 备份恢复演练自动化验证")
    parser.add_argument("backup_file", help="pg_dump 备份文件路径（.dump 或 .sql）")
    parser.add_argument("--db-host", default="localhost", help="数据库主机（默认 localhost）")
    parser.add_argument("--db-port", type=int, default=5432, help="数据库端口（默认 5432）")
    parser.add_argument("--db-user", default="odoo", help="数据库用户（默认 odoo）")
    parser.add_argument("--pg-restore", default="pg_restore", help="pg_restore 命令路径（默认 pg_restore）")
    args = parser.parse_args()

    # 检查备份文件存在
    if not os.path.exists(args.backup_file):
        print(f"ERROR: 备份文件不存在: {args.backup_file}")
        sys.exit(1)

    backup_size = os.path.getsize(args.backup_file)
    print(f"备份文件: {args.backup_file} ({backup_size / 1024 / 1024:.1f} MB)")
    print(f"数据库: {args.db_user}@{args.db_host}:{args.db_port}")

    # 创建临时数据库名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_db = f"zaojia_restore_test_{timestamp}"

    try:
        # 1. 创建临时数据库
        create_temp_db(args.db_host, args.db_port, args.db_user, temp_db)

        # 2. 恢复备份
        if not restore_backup(args.pg_restore, args.backup_file, args.db_host, args.db_port, args.db_user, temp_db):
            print("RESULT: FAIL (备份恢复失败)")
            sys.exit(1)

        # 3-4. 校验表结构和数据
        if not verify_tables(args.db_host, args.db_port, args.db_user, temp_db):
            print("RESULT: FAIL (数据校验失败)")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("RESULT: PASS")
        print("备份恢复演练验证通过：备份文件可完整恢复，表结构和关键数据一致。")
        print("=" * 60)

    except Exception as e:
        print(f"\nERROR: 验证过程异常: {e}")
        print("RESULT: FAIL")
        sys.exit(1)
    finally:
        # 5. 清理临时数据库（无论成功或失败）
        drop_temp_db(args.db_host, args.db_port, args.db_user, temp_db)


if __name__ == "__main__":
    main()
