import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine, Base
from app.models import list_material_mapping
from sqlalchemy import inspect

# 检查模型字段
print('模型字段:')
for col in list_material_mapping.ListMaterialMapping.__table__.columns:
    print(f'  {col.name}: {col.type}')

# 检查数据库中是否有表
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f'\n数据库中表数量: {len(tables)}')
if 'list_material_mapping' in tables:
    print('list_material_mapping 表已存在')
    cols = inspector.get_columns('list_material_mapping')
    print('表字段:')
    for col in cols:
        print(f'  {col["name"]}: {col["type"]}')
else:
    print('list_material_mapping 表不存在')

# 强制删除并重新创建
print('\n强制删除并重新创建表...')
with engine.connect() as conn:
    conn.execute('DROP TABLE IF EXISTS list_material_mapping CASCADE')
    conn.commit()

Base.metadata.create_all(bind=engine, tables=[list_material_mapping.ListMaterialMapping.__table__])

# 验证
inspector2 = inspect(engine)
if 'list_material_mapping' in inspector2.get_table_names():
    cols = inspector2.get_columns('list_material_mapping')
    print('\n新表字段:')
    for col in cols:
        print(f'  {col["name"]}: {col["type"]}')
    print('\n表创建成功！')
else:
    print('\n表创建失败！')
