# -*- coding: utf-8 -*-
"""修复 material_dict 表的父子层级关系。

根因：329个节点的层级标记与编码长度不匹配（全部标记为l4，但编码长度对应l2/l3/l5）。
修复方案：
1. 根据编码长度重新设置层级标记（3-2-2-3-4编码方案）
   - I+3位(4字符) → l1
   - I+5位(6字符) → l2
   - I+7位(8字符) → l3
   - I+10位(11字符) → l4
   - I+14位(15字符) → l5
2. 根据编码前缀重新确定parent_id（找到编码长度少一级的前缀对应的节点）
3. 无编码的节点保持原样
"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal, engine
from app.models.material_dict import MaterialDict
from sqlalchemy import text

# 编码长度 -> 层级映射（含前缀I）
CODE_LEN_TO_LEVEL = {
    4: 'l1',   # I + 3位
    6: 'l2',   # I + 5位
    8: 'l3',   # I + 7位
    11: 'l4',  # I + 10位
    15: 'l5',  # I + 14位
}

# 层级 -> 父级编码长度（去掉最后一段）
LEVEL_TO_PARENT_CODE_LEN = {
    'l2': 4,   # l2的父级编码长度=4(l1)
    'l3': 6,   # l3的父级编码长度=6(l2)
    'l4': 8,   # l4的父级编码长度=8(l3)
    'l5': 11,  # l5的父级编码长度=11(l4)
}

db = SessionLocal()

try:
    print("加载所有节点...")
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                          MaterialDict.level, MaterialDict.parent_id).all()
    print(f"总节点数: {len(all_nodes)}")

    # 构建 code -> id 映射
    code_to_id = {n.code: n.id for n in all_nodes if n.code}
    print(f"有编码的节点数: {len(code_to_id)}")

    # 统计修复前的层级分布
    print("\n修复前层级分布:")
    level_count_before = {}
    for n in all_nodes:
        level_count_before[n.level] = level_count_before.get(n.level, 0) + 1
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        print(f"  {lv}: {level_count_before.get(lv, 0)}")

    # 修复：根据编码长度重新设置层级和parent_id
    level_fixed = 0
    parent_fixed = 0
    both_fixed = 0
    update_batch = []  # (id, new_level, new_parent_id)

    for n in all_nodes:
        if not n.code:
            continue  # 无编码的节点保持原样

        code_len = len(n.code)
        expected_level = CODE_LEN_TO_LEVEL.get(code_len)
        if expected_level is None:
            print(f"  ⚠️ 未知编码长度: {n.code} ({code_len}字符), id={n.id}")
            continue

        new_level = expected_level
        new_parent_id = n.parent_id

        # 重新确定parent_id
        if new_level != 'l1':
            parent_code_len = LEVEL_TO_PARENT_CODE_LEN.get(new_level)
            if parent_code_len and len(n.code) > parent_code_len:
                parent_code = n.code[:parent_code_len]
                new_parent_id = code_to_id.get(parent_code)
                if new_parent_id is None:
                    print(f"  ⚠️ 未找到父级编码: {parent_code} (子节点 {n.code}), id={n.id}")
                    new_parent_id = n.parent_id  # 保持原样

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

    print(f"\n修复统计:")
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
                        "UPDATE material_dict SET level=:lv WHERE id=:id"
                    ), {'lv': new_level, 'id': nid})
        print("✅ 更新完成")

    # 验证修复后的层级分布
    print("\n修复后层级分布:")
    db.expire_all()
    all_nodes2 = db.query(MaterialDict.level).all()
    level_count_after = {}
    for n in all_nodes2:
        level_count_after[n.level] = level_count_after.get(n.level, 0) + 1
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        print(f"  {lv}: {level_count_after.get(lv, 0)}")

    # 验证父子关系
    print("\n验证父子关系（抽样）:")
    by_id2 = {n.id: n for n in db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                                           MaterialDict.level, MaterialDict.parent_id).all()}
    cross_errors = 0
    for n in by_id2.values():
        if n.level == 'l1' or n.parent_id is None:
            continue
        parent = by_id2.get(n.parent_id)
        if parent is None:
            cross_errors += 1
        elif int(parent.level[1]) != int(n.level[1]) - 1:
            cross_errors += 1
    print(f"  跨层级错误数: {cross_errors}")
    if cross_errors == 0:
        print("  ✅ 父子层级关系验证通过！")

finally:
    db.close()
