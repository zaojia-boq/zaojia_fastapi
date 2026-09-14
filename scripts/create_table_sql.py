import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine, settings
from sqlalchemy import text, inspect

print(f'数据库URL: {settings.database_url}')
print(f'引擎: {engine.url}')

# 用原生SQL删除并创建表
with engine.connect() as conn:
    # 删除旧表
    conn.execute(text('DROP TABLE IF EXISTS list_material_mapping CASCADE'))
    conn.commit()
    print('旧表已删除')

    # 创建新表
    create_sql = '''
    CREATE TABLE list_material_mapping (
        id SERIAL PRIMARY KEY,
        list_version VARCHAR(8) NOT NULL DEFAULT '2024',
        list_item_code VARCHAR(32) NOT NULL,
        list_item_name VARCHAR NOT NULL,
        material_code VARCHAR(32) NOT NULL,
        material_name VARCHAR NOT NULL,
        match_type VARCHAR(32) NOT NULL,
        similarity FLOAT NOT NULL DEFAULT 0.0,
        biz_id VARCHAR(36),
        create_date TIMESTAMP,
        write_date TIMESTAMP
    )
    '''
    conn.execute(text(create_sql))
    conn.commit()
    print('新表已创建')

    # 创建索引
    conn.execute(text('CREATE INDEX ix_list_material_mapping_list_version ON list_material_mapping (list_version)'))
    conn.execute(text('CREATE INDEX ix_list_material_mapping_list_item_code ON list_material_mapping (list_item_code)'))
    conn.execute(text('CREATE INDEX ix_list_material_mapping_material_code ON list_material_mapping (material_code)'))
    conn.commit()
    print('索引已创建')

# 验证
inspector = inspect(engine)
cols = inspector.get_columns('list_material_mapping')
print('\n表字段:')
for col in cols:
    print(f'  {col["name"]}: {col["type"]}')

print('\n表创建成功！')
