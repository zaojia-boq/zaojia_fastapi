# -*- coding: utf-8 -*-
"""根据v5数据的编码+父编码关系，同时修复material_dict表的level和parent_id。

修复逻辑：
1. 加载v5数据，构建 code -> (level标记, 父编码) 映射
2. 构建 code -> 数据库id 映射
3. 对于数据库中有code的节点：
   - 从v5数据获取正确的层级标记和父编码
   - 根据父编码找到父节点的数据库id
   - 同时更新level和parent_id
4. 无code的节点保持原样
"""
import sys
import gzip
import json
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal, engine
from app.models.material_dict import MaterialDict
from sqlalchemy import text

v5_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'

print("加载v5数据...")
with gzip.open(v5_path, 'rt', encoding='utf-8') as f:
    v5_data = json.load(f)
print(f"v5数据总条数: {len(v5_data)}")

# 构建 code -> (level, parent_code) 映射
v5_map = {}
for item in v5_data:
    code = item.get('编码', '')
    if code:
        level = f"l{item.get('层级', '')}"
        parent_code = item.get('父编码', '')
        v5_map[code] = (level, parent_code)
print(f"v5编码映射数: {len(v5_map)}")

# 加载数据库所有节点
db = SessionLocal()
try:
    print("加载数据库节点...")
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                          MaterialDict.level, MaterialDict.parent_id).all()
    print(f"数据库节点数: {len(all_nodes)}")

    # 构建 code -> id 映射
    code_to_id = {n.code: n.id for n in all_nodes if n.code}
    print(f"有编码的节点数: {len(code_to_id)}")

    # 统计修复前的错误
    print("\n修复前跨层级错误统计:")
    by_id = {n.id: n for n in all_nodes}
    cross_before = 0
    for n in all_nodes:
        if n.level == 'l1' or n.parent_id is None:
            continue
        parent = by_id.get(n.parent_id)
        if parent is None or int(parent.level[1]) != int(n.level[1]) - 1:
            cross_before += 1
    print(f"  跨层级错误: {cross_before}")

    # 执行修复
    print("\n执行修复...")
    level_fixed = 0
    parent_fixed = 0
    both_fixed = 0
    no_v5 = 0
    no_parent = 0
    update_batch = []

    for n in all_nodes:
        if not n.code:
            continue
        v5_info = v5_map.get(n.code)
        if not v5_info:
            no_v5 += 1
            continue
        new_level, parent_code = v5_info

        # 找父节点id
        new_parent_id = None
        if parent_code and parent_code in code_to_id:
            new_parent_id = code_to_id[parent_code]
        elif not parent_code:
            new_parent_id = None  # 根节点
        else:
            no_parent += 1
            # 父编码不在数据库中，保持原parent_id
            new_parent_id = n.parent_id

        # 判断是否需要更新
        level_changed = (new_level != n.level)
        parent_changed = (new_parent_id != n.parent_id)

        if level_changed or parent_changed:
            if level_changed and parent_changed:
                both_fixed += 1
            elif level_changed:
                level_fixed += 1
            elif parent_changed:
                parent_fixed += 1
            update_batch.append((n.id, new_level, new_parent_id))

    print(f"  v5中无对应编码: {no_v5}")
    print(f"  父编码不在数据库: {no_parent}")
    print(f"  仅层级修正: {level_fixed}")
    print(f"  仅parent_id修正: {parent_fixed}")
    print(f"  层级+parent_id同时修正: {both_fixed}")
    print(f"  总计更新: {len(update_batch)}")

    # 执行批量更新
    if update_batch:
        print(f"\n执行批量更新 {len(update_batch)} 条...")
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
    level_count = {}
    for n in all_nodes2:
        level_count[n.level] = level_count.get(n.level, 0) + 1
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        print(f"  {lv}: {level_count.get(lv, 0)}")

    # 验证修复后的跨层级错误
    print("\n验证修复后的跨层级错误:")
    by_id2 = {n.id: n for n in db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                                           MaterialDict.level, MaterialDict.parent_id).all()}
    cross_after = 0
    orphan_after = 0
    for n in by_id2.values():
        if n.level == 'l1' or n.parent_id is None:
            continue
        parent = by_id2.get(n.parent_id)
        if parent is None:
            orphan_after += 1
        elif int(parent.level[1]) != int(n.level[1]) - 1:
            cross_after += 1
    print(f"  跨层级错误: {cross_after}")
    print(f"  孤立节点: {orphan_after}")
    if cross_after == 0 and orphan_after == 0:
        print("  ✅ 父子层级关系验证全部通过！")

finally:
    db.close()
