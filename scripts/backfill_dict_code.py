# -*- coding: utf-8 -*-
"""给 material_dict 表加 code 列，并从 v5 数据回填五级编码（3-2-2-3-4）。

匹配策略：按层级从 l1→l5 逐级匹配，构建 (name, level, parent_id) → code 映射。
- l1：按 name 唯一匹配
- l2-l5：按 (name, parent_id) 匹配（同一父级下名称唯一）
"""
import gzip
import json
import sys
from collections import defaultdict

sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine, SessionLocal
from app.models.material_dict import MaterialDict
from sqlalchemy import text

V5_PATH = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'

db = SessionLocal()

try:
    # 1. 加列（如果不存在）
    with engine.begin() as conn:
        cols = [r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='material_dict'"
        )).fetchall()]
        if 'code' not in cols:
            conn.execute(text("ALTER TABLE material_dict ADD COLUMN code VARCHAR(32)"))
            print("✅ 已添加 code 列")
        else:
            print("ℹ️ code 列已存在")
        # 加唯一索引（NULL 不冲突）
        idx_exists = conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE tablename='material_dict' AND indexname='ix_material_dict_code'"
        )).fetchone()
        if not idx_exists:
            conn.execute(text(
                "CREATE UNIQUE INDEX ix_material_dict_code ON material_dict(code) WHERE code IS NOT NULL"
            ))
            print("✅ 已添加 code 唯一索引")

    # 2. 读取 v5 数据
    print(f"\n读取 v5 数据: {V5_PATH}")
    with gzip.open(V5_PATH, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get('items', data.get('data', []))
    print(f"v5 总条数: {len(items)}")

    # 按层级分组
    by_level = defaultdict(list)
    for it in items:
        by_level[it['层级']].append(it)
    for lv in sorted(by_level.keys()):
        print(f"  层级 {lv}: {len(by_level[lv])} 条")

    # 3. 逐级匹配构建 code→id 映射
    code_to_id = {}       # 编码 → 数据库 id
    name_to_id_l1 = {}    # l1: name → id
    parent_child_map = defaultdict(dict)  # parent_id → {name → id}

    # 先加载数据库所有节点
    print("\n加载数据库节点...")
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.level, MaterialDict.parent_id).all()
    print(f"数据库总节点: {len(all_nodes)}")

    db_by_id = {n.id: n for n in all_nodes}
    for n in all_nodes:
        if n.level == 'l1':
            name_to_id_l1[n.name] = n.id
        else:
            parent_child_map[n.parent_id][n.name] = n.id

    # 逐级匹配
    level_map = {1: 'l1', 2: 'l2', 3: 'l3', 4: 'l4', 5: 'l5'}
    matched = 0
    unmatched = 0
    update_batch = []  # (id, code)

    for lv in sorted(by_level.keys()):
        db_level = level_map.get(lv, f'l{lv}')
        lv_matched = 0
        lv_unmatched = 0
        for it in by_level[lv]:
            code = it['编码']
            name = it['名称']
            parent_code = it.get('父编码', '')

            if lv == 1:
                nid = name_to_id_l1.get(name)
            else:
                # 找父级 id
                parent_id = code_to_id.get(parent_code)
                if parent_id is None:
                    lv_unmatched += 1
                    continue
                nid = parent_child_map.get(parent_id, {}).get(name)

            if nid is not None:
                code_to_id[code] = nid
                update_batch.append((nid, code))
                lv_matched += 1
            else:
                lv_unmatched += 1

        print(f"  层级 {lv}({db_level}): 匹配 {lv_matched}, 未匹配 {lv_unmatched}")
        matched += lv_matched
        unmatched += lv_unmatched

    print(f"\n总计: 匹配 {matched}, 未匹配 {unmatched}, 匹配率 {matched/(matched+unmatched)*100:.1f}%")

    # 4. 批量更新 code
    if update_batch:
        print(f"\n批量更新 {len(update_batch)} 条记录的 code...")
        with engine.begin() as conn:
            for nid, code in update_batch:
                conn.execute(text("UPDATE material_dict SET code=:c WHERE id=:i"), {'c': code, 'i': nid})
        print("✅ 编码回填完成")

    # 5. 验证
    code_count = db.query(MaterialDict).filter(MaterialDict.code != None).count()
    total = db.query(MaterialDict).count()
    print(f"\n验证: 有 code 的记录 {code_count}/{total} ({code_count/total*100:.1f}%)")

    # 抽样显示
    print("\n抽样（l1-l5 各1条）:")
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        sample = db.query(MaterialDict).filter(
            MaterialDict.level == lv, MaterialDict.code != None
        ).first()
        if sample:
            print(f"  {lv}: {sample.code}  {sample.name}")

finally:
    db.close()
