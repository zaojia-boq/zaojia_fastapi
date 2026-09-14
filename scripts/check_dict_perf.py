"""检查material_dict表的索引和性能"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine
from sqlalchemy import text

with engine.connect() as conn:
    # 检查表索引
    print('=== material_dict 表索引 ===')
    result = conn.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'material_dict'
        ORDER BY indexname
    """))
    for row in result:
        print(f'  {row.indexname}: {row.indexdef[:100]}')

    # 统计各层级数量
    print('\n=== 各层级数量 ===')
    result = conn.execute(text("""
        SELECT level, COUNT(*) as cnt
        FROM material_dict
        GROUP BY level
        ORDER BY level
    """))
    for row in result:
        print(f'  {row.level}: {row.cnt:,}')

    # 测试L1查询性能（不带exists）
    print('\n=== L1查询性能测试（不带hasChild） ===')
    import time
    start = time.time()
    result = conn.execute(text("""
        SELECT id, name, level, parent_id
        FROM material_dict
        WHERE parent_id IS NULL
        ORDER BY name
    """))
    rows = result.fetchall()
    elapsed = time.time() - start
    print(f'  查询时间: {elapsed*1000:.1f}ms, 记录数: {len(rows)}')

    # 测试L1查询性能（带exists）
    print('\n=== L1查询性能测试（带exists hasChild） ===')
    start = time.time()
    result = conn.execute(text("""
        SELECT m.id, m.name, m.level, m.parent_id,
               EXISTS(SELECT 1 FROM material_dict c WHERE c.parent_id = m.id) as has_child
        FROM material_dict m
        WHERE m.parent_id IS NULL
        ORDER BY m.name
    """))
    rows = result.fetchall()
    elapsed = time.time() - start
    print(f'  查询时间: {elapsed*1000:.1f}ms, 记录数: {len(rows)}')

    # 测试L1查询性能（LEFT JOIN + GROUP BY）
    print('\n=== L1查询性能测试（LEFT JOIN + GROUP BY） ===')
    start = time.time()
    result = conn.execute(text("""
        SELECT m.id, m.name, m.level, m.parent_id,
               COUNT(c.id) > 0 as has_child
        FROM material_dict m
        LEFT JOIN material_dict c ON c.parent_id = m.id
        WHERE m.parent_id IS NULL
        GROUP BY m.id, m.name, m.level, m.parent_id
        ORDER BY m.name
    """))
    rows = result.fetchall()
    elapsed = time.time() - start
    print(f'  查询时间: {elapsed*1000:.1f}ms, 记录数: {len(rows)}')

    # 测试某个L3节点的子节点数量（可能很大）
    print('\n=== 子节点数量分布（父节点子节点数TOP10） ===')
    result = conn.execute(text("""
        SELECT parent_id, COUNT(*) as cnt
        FROM material_dict
        WHERE parent_id IS NOT NULL
        GROUP BY parent_id
        ORDER BY cnt DESC
        LIMIT 10
    """))
    for row in result:
        print(f'  parent_id={row.parent_id}: {row.cnt:,} 个子节点')
