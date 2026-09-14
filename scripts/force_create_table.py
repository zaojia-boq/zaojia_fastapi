"""list_material_mapping 表结构检查脚本（只读，不做任何 DDL）。

历史背景：此前此脚本含 `DROP TABLE IF EXISTS ... CASCADE` + `create_all`，
生产误运行会清数据。2026-09-14 起 M6 表回归 Alembic 单轨（迁移 b2c3d4e5f6a7），
此脚本改为只读检查：对比模型字段与数据库实际字段，不一致时报警但不自动修复。

用法：python scripts/force_create_table.py
"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine
from app.models import list_material_mapping
from sqlalchemy import inspect

# 检查模型字段
model = list_material_mapping.ListMaterialMapping
print('模型字段:')
model_cols = {}
for col in model.__table__.columns:
    model_cols[col.name] = str(col.type)
    print(f'  {col.name}: {col.type}')

# 检查数据库中是否有表
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f'\n数据库中表数量: {len(tables)}')

table_name = 'list_material_mapping'
if table_name not in tables:
    print(f'\n[警告] {table_name} 表不存在，请执行: alembic upgrade head')
    sys.exit(1)

print(f'{table_name} 表已存在')
db_cols = {}
for col in inspector.get_columns(table_name):
    db_cols[col['name']] = str(col['type'])
    print(f'  {col["name"]}: {col["type"]}')

# 对比模型与数据库
print('\n字段对比:')
mismatch = False
for name, mtype in model_cols.items():
    if name not in db_cols:
        print(f'  [缺失] 数据库缺少字段: {name} ({mtype})')
        mismatch = True
    elif db_cols[name] != mtype:
        print(f'  [不一致] {name}: 模型={mtype}, 数据库={db_cols[name]}')
        mismatch = True

for name in db_cols:
    if name not in model_cols:
        print(f'  [多余] 数据库有额外字段: {name}')

if not mismatch:
    print('  全部一致 ✅')
else:
    print('\n[警告] 字段不一致，请检查 Alembic 迁移或手动调整。本脚本不自动修复。')
