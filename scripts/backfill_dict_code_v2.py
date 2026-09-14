# -*- coding: utf-8 -*-
"""编码回填 v2：按数据库 id 去重，每个 id 只保留第一个匹配的 code。

v1 问题：v5 l5 规格层有大量重复 (名称, 父编码)，匹配到同一数据库 id，
update_batch 中 id 重复导致唯一 id 仅 27,427 个（应 155,359）。
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
    # 1. 读取 v5 数据
    print(f"读取 v5 数据...")
    with gzip.open(V5_PATH, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get('items', data.get('data', []))
    print(f"v5 总条数: {len(items)}")

    # 2. 加载数据库节点
    print("加载数据库节点...")
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.level, MaterialDict.parent_id).all()
    print(f"数据库总节点: {len(all_nodes)}")

    name_to_id_l1 = {}
    parent_child_map = defaultdict(dict)
    for n in all_nodes:
        if n.level == 'l1':
            name_to_id_l1[n.name] = n.id
        else:
            parent_child_map[n.parent_id][n.name] = n.id

    # 3. 逐级匹配，按数据库 id 去重（每个 id 只保留第一个 code）
    level_map = {1: 'l1', 2: 'l2', 3: 'l3', 4: 'l4', 5: 'l5'}
    by_level = defaultdict(list)
    for it in items:
        by_level[it['层级']].append(it)

    code_to_id = {}
    id_to_code = {}  # 关键：按 id 去重，每个 id 只保留第一个 code
    matched = 0
    unmatched = 0

    for lv in sorted(by_level.keys()):
        lv_matched = 0
        lv_unmatched = 0
        for it in by_level[lv]:
            code = it['编码']
            name = it['名称']
            parent_code = it.get('父编码', '')

            if lv == 1:
                nid = name_to_id_l1.get(name)
            else:
                parent_id = code_to_id.get(parent_code)
                if parent_id is None:
                    lv_unmatched += 1
                    continue
                nid = parent_child_map.get(parent_id, {}).get(name)

            if nid is not None:
                code_to_id[code] = nid
                if nid not in id_to_code:  # 按 id 去重
                    id_to_code[nid] = code
                lv_matched += 1
            else:
                lv_unmatched += 1

        print(f"  层级 {lv}: 匹配 {lv_matched}, 未匹配 {lv_unmatched}")
        matched += lv_matched
        unmatched += lv_unmatched

    print(f"\n总计: 匹配 {matched}, 未匹配 {unmatched}")
    print(f"唯一数据库 id 数: {len(id_to_code)}")

    # 4. 先清空所有 code，再全量更新
    print("\n清空旧 code...")
    with engine.begin() as conn:
        conn.execute(text("UPDATE material_dict SET code=NULL"))

    print(f"批量更新 {len(id_to_code)} 条记录的 code...")
    update_batch = [(nid, code) for nid, code in id_to_code.items()]
    BATCH = 5000
    with engine.begin() as conn:
        for i in range(0, len(update_batch), BATCH):
            chunk = update_batch[i:i+BATCH]
            # 用 CASE WHEN 批量更新
            when_clauses = " ".join(f"WHEN {nid} THEN '{code}'" for nid, code in chunk)
            ids = ",".join(str(nid) for nid, _ in chunk)
            sql = f"UPDATE material_dict SET code = CASE id {when_clauses} END WHERE id IN ({ids})"
            conn.execute(text(sql))
            print(f"  已更新 {min(i+BATCH, len(update_batch))}/{len(update_batch)}")

    print("✅ 编码回填完成")

    # 5. 验证
    code_count = db.query(MaterialDict).filter(MaterialDict.code != None).count()
    total = db.query(MaterialDict).count()
    print(f"\n验证: 有 code 的记录 {code_count}/{total} ({code_count/total*100:.1f}%)")

    by_lv = db.query(MaterialDict.level, func.count(MaterialDict.id), func.count(MaterialDict.code)).group_by(MaterialDict.level).all()
    from sqlalchemy import func
    for r in by_lv:
        print(f"  {r[0]}: 总{r[1]}, 有code={r[2]} ({r[2]/r[1]*100:.1f}%)")

    print("\n抽样:")
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        sample = db.query(MaterialDict).filter(MaterialDict.level == lv, MaterialDict.code != None).first()
        if sample:
            print(f"  {lv}: {sample.code}  {sample.name}")

finally:
    db.close()
