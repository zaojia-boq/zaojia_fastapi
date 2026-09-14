# -*- coding: utf-8 -*-
"""根据编码长度修正material_dict表的层级标记。

编码长度到层级的映射（标准3-2-2-3-4方案）：
- 4字符(I+3位) → l1
- 6字符(I+5位) → l2
- 8字符(I+7位) → l3
- 11字符(I+10位) → l4
- 15字符(I+14位) → l5

非标准编码长度(10/12/19字符)保持原层级（经验证它们的层级关系正确）。

同时根据编码前缀修正parent_id：
- 子编码去掉最后一段，得到父编码
- 根据父编码找到父节点id
"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal, engine
from app.models.material_dict import MaterialDict
from sqlalchemy import text

# 标准编码长度到层级的映射
CODE_LEN_TO_LEVEL = {
    4: 'l1',
    6: 'l2',
    8: 'l3',
    11: 'l4',
    15: 'l5',
}

# 层级到父编码长度的映射
LEVEL_TO_PARENT_LEN = {
    'l2': 4,   # l2的父编码长度=4(l1)
    'l3': 6,   # l3的父编码长度=6(l2)
    'l4': 8,   # l4的父编码长度=8(l3)
    'l5': 11,  # l5的父编码长度=11(l4)
}

db = SessionLocal()
try:
    print("加载数据库节点...")
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                          MaterialDict.level, MaterialDict.parent_id).all()
    print(f"总节点数: {len(all_nodes)}")

    # 构建 code -> id 映射
    code_to_id = {n.code: n.id for n in all_nodes if n.code}
    print(f"有编码的节点数: {len(code_to_id)}")

    # 统计修复前的层级分布
    print("\n修复前层级分布:")
    level_before = {}
    for n in all_nodes:
        level_before[n.level] = level_before.get(n.level, 0) + 1
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        print(f"  {lv}: {level_before.get(lv, 0)}")

    # 执行修复
    print("\n执行修复...")
    level_fixed = 0
    parent_fixed = 0
    both_fixed = 0
    non_standard = 0
    no_parent = 0
    update_batch = []

    for n in all_nodes:
        if not n.code:
            continue

        code_len = len(n.code)
        expected_level = CODE_LEN_TO_LEVEL.get(code_len)

        if expected_level is None:
            # 非标准编码长度，保持原样
            non_standard += 1
            continue

        new_level = expected_level

        # 根据编码前缀确定parent_id
        new_parent_id = n.parent_id
        if new_level != 'l1':
            parent_len = LEVEL_TO_PARENT_LEN.get(new_level)
            if parent_len and len(n.code) > parent_len:
                parent_code = n.code[:parent_len]
                if parent_code in code_to_id:
                    new_parent_id = code_to_id[parent_code]
                else:
                    no_parent += 1
                    # 父编码不在数据库中，保持原parent_id
        else:
            new_parent_id = None  # l1的parent_id为NULL

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

    print(f"  非标准编码长度（保持原样）: {non_standard}")
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
