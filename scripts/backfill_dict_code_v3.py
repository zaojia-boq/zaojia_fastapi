# -*- coding: utf-8 -*-
"""编码回填 v3：l1-l4 按名称匹配，l5 按父级分组后按顺序一一对应。

v2 问题：v5 l5 有大量重复 (名称,父编码)，按名称匹配时多个 v5 条目命中同一数据库 id，
导致唯一 id 仅 27,427。v3 对 l5 改用按父级分组+顺序一一对应。
"""
import gzip
import json
import sys
from collections import defaultdict

sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine, SessionLocal
from app.models.material_dict import MaterialDict
from sqlalchemy import text, func

V5_PATH = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'

db = SessionLocal()

try:
    # 1. 读取 v5 数据
    print("读取 v5 数据...")
    with gzip.open(V5_PATH, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get('items', data.get('data', []))
    print(f"v5 总条数: {len(items)}")

    by_level = defaultdict(list)
    for it in items:
        by_level[it['层级']].append(it)

    # 2. 加载数据库节点
    print("加载数据库节点...")
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.level, MaterialDict.parent_id).all()
    print(f"数据库总节点: {len(all_nodes)}")

    db_by_id = {n.id: n for n in all_nodes}
    name_to_id_l1 = {}
    parent_child_map = defaultdict(dict)  # parent_id -> {name -> [ids]}（l5可能有重复，用list）
    parent_child_ids = defaultdict(list)   # parent_id -> [ids按id顺序]

    for n in all_nodes:
        if n.level == 'l1':
            name_to_id_l1[n.name] = n.id
        elif n.level in ('l2', 'l3', 'l4'):
            parent_child_map[n.parent_id][n.name] = n.id
        elif n.level == 'l5':
            parent_child_ids[n.parent_id].append(n.id)  # 按查询顺序（id升序）

    # 3. l1-l4 按名称匹配
    level_map = {1: 'l1', 2: 'l2', 3: 'l3', 4: 'l4', 5: 'l5'}
    code_to_id = {}
    id_to_code = {}

    for lv in [1, 2, 3, 4]:
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
                id_to_code[nid] = code
                lv_matched += 1
            else:
                lv_unmatched += 1

        print(f"  l{lv}: 匹配 {lv_matched}, 未匹配 {lv_unmatched}")

    # 4. l5 按父级分组后按顺序一一对应
    print("\n处理 l5（按父级分组+顺序对应）...")
    # 按父编码分组 v5 l5 条目，保持原始顺序
    v5_l5_by_parent = defaultdict(list)
    for it in by_level[5]:
        v5_l5_by_parent[it.get('父编码', '')].append(it['编码'])

    l5_matched = 0
    l5_unmatched = 0
    for parent_code, v5_codes in v5_l5_by_parent.items():
        parent_id = code_to_id.get(parent_code)
        if parent_id is None:
            l5_unmatched += len(v5_codes)
            continue
        # 数据库中该父级下的 l5 id 列表（按id顺序）
        db_ids = parent_child_ids.get(parent_id, [])
        # 按顺序一一对应
        for i, v5_code in enumerate(v5_codes):
            if i < len(db_ids):
                nid = db_ids[i]
                code_to_id[v5_code] = nid
                if nid not in id_to_code:  # 避免覆盖l1-l4已分配的
                    id_to_code[nid] = v5_code
                l5_matched += 1
            else:
                l5_unmatched += 1

    print(f"  l5: 匹配 {l5_matched}, 未匹配 {l5_unmatched}")
    print(f"\n总计唯一数据库 id 数: {len(id_to_code)}")

    # 5. 清空旧 code，全量更新
    print("\n清空旧 code...")
    with engine.begin() as conn:
        conn.execute(text("UPDATE material_dict SET code=NULL"))

    print(f"批量更新 {len(id_to_code)} 条...")
    update_batch = [(nid, code) for nid, code in id_to_code.items()]
    BATCH = 5000
    with engine.begin() as conn:
        for i in range(0, len(update_batch), BATCH):
            chunk = update_batch[i:i+BATCH]
            when_clauses = " ".join(f"WHEN {nid} THEN '{code}'" for nid, code in chunk)
            ids = ",".join(str(nid) for nid, _ in chunk)
            sql = f"UPDATE material_dict SET code = CASE id {when_clauses} END WHERE id IN ({ids})"
            conn.execute(text(sql))
            print(f"  已更新 {min(i+BATCH, len(update_batch))}/{len(update_batch)}")

    print("✅ 编码回填完成")

    # 6. 验证
    code_count = db.query(MaterialDict).filter(MaterialDict.code != None).count()
    total = db.query(MaterialDict).count()
    print(f"\n验证: 有 code {code_count}/{total} ({code_count/total*100:.1f}%)")

    by_lv = db.query(MaterialDict.level, func.count(MaterialDict.id), func.count(MaterialDict.code)).group_by(MaterialDict.level).all()
    for r in by_lv:
        print(f"  {r[0]}: 总{r[1]}, 有code={r[2]} ({r[2]/r[1]*100:.1f}%)")

    print("\n抽样:")
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        samples = db.query(MaterialDict).filter(MaterialDict.level == lv, MaterialDict.code != None).limit(2).all()
        for s in samples:
            print(f"  {lv}: {s.code}  {s.name}")

finally:
    db.close()
