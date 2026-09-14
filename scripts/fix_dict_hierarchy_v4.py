# -*- coding: utf-8 -*-
"""修复material_dict表的层级关系：先确定正确的parent_id，再级联计算层级。

步骤：
1. 根据编码前缀确定正确的parent_id（标准编码长度）
2. 对于非标准编码长度，根据v5数据的父编码字段确定parent_id
3. 从根节点（parent_id=NULL）开始，级联计算所有节点的层级
   - 根节点 → l1
   - 父节点是l1 → l2
   - 父节点是l2 → l3
   - 父节点是l3 → l4
   - 父节点是l4 → l5
"""
import sys
import gzip
import json
from collections import deque
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal, engine
from app.models.material_dict import MaterialDict
from sqlalchemy import text

v5_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'

# 标准编码长度到父编码长度的映射（3-2-2-3-4方案）
STANDARD_PARENT_LEN = {
    6: 4,   # 6字符(I+5位)的父编码长度=4(I+3位)
    8: 6,   # 8字符(I+7位)的父编码长度=6(I+5位)
    11: 8,  # 11字符(I+10位)的父编码长度=8(I+7位)
    15: 11, # 15字符(I+14位)的父编码长度=11(I+10位)
}

db = SessionLocal()
try:
    print("加载v5数据...")
    with gzip.open(v5_path, 'rt', encoding='utf-8') as f:
        v5_data = json.load(f)
    v5_parent_code = {item['编码']: item.get('父编码', '') for item in v5_data if item.get('编码')}
    print(f"v5编码映射数: {len(v5_parent_code)}")

    print("加载数据库节点...")
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                          MaterialDict.level, MaterialDict.parent_id).all()
    print(f"总节点数: {len(all_nodes)}")

    # 构建 code -> id 映射
    code_to_id = {n.code: n.id for n in all_nodes if n.code}
    print(f"有编码的节点数: {len(code_to_id)}")

    # 步骤1：确定正确的parent_id
    print("\n步骤1：确定正确的parent_id...")
    correct_parent = {}  # id -> correct parent_id
    no_parent_code = 0
    for n in all_nodes:
        if not n.code:
            correct_parent[n.id] = n.parent_id
            continue
        code_len = len(n.code)
        parent_code = None

        if code_len == 4:
            # l1根节点，parent_id为NULL
            parent_code = None
        elif code_len in STANDARD_PARENT_LEN:
            # 标准编码长度，根据前缀确定父编码
            parent_len = STANDARD_PARENT_LEN[code_len]
            parent_code = n.code[:parent_len]
        else:
            # 非标准编码长度，根据v5数据的父编码字段
            parent_code = v5_parent_code.get(n.code)

        if parent_code is None:
            correct_parent[n.id] = None
        elif parent_code in code_to_id:
            correct_parent[n.id] = code_to_id[parent_code]
        else:
            no_parent_code += 1
            correct_parent[n.id] = n.parent_id  # 保持原parent_id

    print(f"  父编码不在数据库: {no_parent_code}")

    # 步骤2：从根节点级联计算层级
    print("\n步骤2：从根节点级联计算层级...")
    # 构建 children 映射
    children = {}
    for nid, pid in correct_parent.items():
        if pid is not None:
            children.setdefault(pid, []).append(nid)

    # BFS级联计算层级
    correct_level = {}
    queue = deque()
    # 根节点
    for n in all_nodes:
        if correct_parent[n.id] is None:
            correct_level[n.id] = 'l1'
            queue.append(n.id)

    while queue:
        pid = queue.popleft()
        parent_level = correct_level[pid]
        parent_level_num = int(parent_level[1])
        child_level = f'l{parent_level_num + 1}'
        for cid in children.get(pid, []):
            if cid not in correct_level:
                correct_level[cid] = child_level
                queue.append(cid)

    # 检查是否有未计算层级的节点（孤立节点）
    unleveled = [n.id for n in all_nodes if n.id not in correct_level]
    print(f"  未计算层级的节点: {len(unleveled)}")
    if unleveled:
        for nid in unleveled[:5]:
            n = next(n for n in all_nodes if n.id == nid)
            print(f"    id={nid} [{n.code}] {n.name}, parent_id={correct_parent[nid]}")

    # 步骤3：统计需要更新的节点
    print("\n步骤3：统计更新...")
    level_fixed = 0
    parent_fixed = 0
    both_fixed = 0
    update_batch = []

    for n in all_nodes:
        new_level = correct_level.get(n.id, n.level)
        new_parent = correct_parent.get(n.id, n.parent_id)
        level_changed = (new_level != n.level)
        parent_changed = (new_parent != n.parent_id)

        if level_changed or parent_changed:
            if level_changed and parent_changed:
                both_fixed += 1
            elif level_changed:
                level_fixed += 1
            elif parent_changed:
                parent_fixed += 1
            update_batch.append((n.id, new_level, new_parent))

    print(f"  仅层级修正: {level_fixed}")
    print(f"  仅parent_id修正: {parent_fixed}")
    print(f"  层级+parent_id同时修正: {both_fixed}")
    print(f"  总计更新: {len(update_batch)}")

    # 步骤4：执行批量更新
    if update_batch:
        print(f"\n步骤4：执行批量更新 {len(update_batch)} 条...")
        with engine.begin() as conn:
            for nid, new_level, new_parent_id in update_batch:
                if new_parent_id is not None:
                    conn.execute(text(
                        "UPDATE material_dict SET level=:lv, parent_id=:pid WHERE id=:id"
                    ), {'lv': new_level, 'pid': new_parent_id, 'id': nid})
                else:
                    conn.execute(text(
                        "UPDATE material_dict SET level=:lv, parent_id=NULL WHERE id=:id"
                    ), {'lv': new_level, 'id': nid})
        print("✅ 更新完成")

    # 验证修复后的层级分布
    print("\n修复后层级分布:")
    db.expire_all()
    all_nodes2 = db.query(MaterialDict.level).all()
    level_after = {}
    for n in all_nodes2:
        level_after[n.level] = level_after.get(n.level, 0) + 1
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        print(f"  {lv}: {level_after.get(lv, 0)}")

    # 验证修复后的跨层级错误
    print("\n验证修复后的跨层级错误:")
    by_id2 = {n.id: n for n in db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                                           MaterialDict.level, MaterialDict.parent_id).all()}
    cross_after = 0
    orphan_after = 0
    l1_bad = 0
    for n in by_id2.values():
        if n.level == 'l1':
            if n.parent_id is not None:
                l1_bad += 1
            continue
        if n.parent_id is None:
            continue
        parent = by_id2.get(n.parent_id)
        if parent is None:
            orphan_after += 1
        elif int(parent.level[1]) != int(n.level[1]) - 1:
            cross_after += 1
    print(f"  l1 parent_id非NULL: {l1_bad}")
    print(f"  跨层级错误: {cross_after}")
    print(f"  孤立节点: {orphan_after}")
    if cross_after == 0 and orphan_after == 0 and l1_bad == 0:
        print("  ✅ 父子层级关系验证全部通过！")

finally:
    db.close()
