# -*- coding: utf-8 -*-
"""验证 material_dict 表的父子层级关系完整性。

检查项：
1. l1 的 parent_id 必须为 NULL
2. l2-l5 的 parent_id 必须指向上一层级（l2→l1, l3→l2, l4→l3, l5→l4）
3. 无孤立节点（parent_id 指向不存在的 id）
4. 编码层级关系与 parent_id 一致（如 I00101 的父编码 I001 对应的节点应是其父节点）
5. 每个父节点的子节点层级正确
"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.material_dict import MaterialDict
from sqlalchemy import func

db = SessionLocal()

try:
    print("=" * 70)
    print("material_dict 父子层级关系验证")
    print("=" * 70)

    # 加载所有节点
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                          MaterialDict.level, MaterialDict.parent_id).all()
    print(f"\n总节点数: {len(all_nodes)}")

    by_id = {n.id: n for n in all_nodes}
    level_order = {'l1': 1, 'l2': 2, 'l3': 3, 'l4': 4, 'l5': 5}

    # === 检查1: l1 parent_id 必须为 NULL ===
    print("\n--- 检查1: l1 parent_id 必须为 NULL ---")
    l1_bad = [n for n in all_nodes if n.level == 'l1' and n.parent_id is not None]
    print(f"  l1 总数: {sum(1 for n in all_nodes if n.level=='l1')}")
    print(f"  parent_id 非 NULL 的 l1: {len(l1_bad)}")
    if l1_bad:
        for n in l1_bad[:5]:
            print(f"    ❌ id={n.id} [{n.code}] {n.name}, parent_id={n.parent_id}")

    # === 检查2: l2-l5 parent_id 必须指向上一层级 ===
    print("\n--- 检查2: l2-l5 parent_id 必须指向上一层级 ---")
    expected_parent = {'l2': 'l1', 'l3': 'l2', 'l4': 'l3', 'l5': 'l4'}
    cross_level_errors = []
    for n in all_nodes:
        if n.level in expected_parent and n.parent_id is not None:
            parent = by_id.get(n.parent_id)
            if parent is None:
                cross_level_errors.append((n, 'orphan'))
            elif parent.level != expected_parent[n.level]:
                cross_level_errors.append((n, f'cross:{parent.level}'))
    print(f"  跨层级/孤立错误数: {len(cross_level_errors)}")
    if cross_level_errors:
        for n, err in cross_level_errors[:10]:
            pname = by_id[n.parent_id].name if n.parent_id in by_id else 'NOT FOUND'
            print(f"    ❌ {n.level} [{n.code}] {n.name} -> parent_id={n.parent_id} ({pname}) [{err}]")

    # === 检查3: 无孤立节点（parent_id 指向不存在的 id）===
    print("\n--- 检查3: 无孤立节点 ---")
    orphans = [n for n in all_nodes if n.parent_id is not None and n.parent_id not in by_id]
    print(f"  孤立节点数: {len(orphans)}")
    if orphans:
        for n in orphans[:5]:
            print(f"    ❌ id={n.id} [{n.code}] {n.name}, parent_id={n.parent_id} 不存在")

    # === 检查4: 编码层级关系与 parent_id 一致 ===
    print("\n--- 检查4: 编码层级关系与 parent_id 一致 ---")
    # 构建 code -> node 映射
    by_code = {n.code: n for n in all_nodes if n.code}
    code_mismatch = []
    for n in all_nodes:
        if not n.code or n.level == 'l1' or n.parent_id is None:
            continue
        parent = by_id.get(n.parent_id)
        if parent and parent.code:
            # 子编码应该以父编码开头
            if not n.code.startswith(parent.code):
                code_mismatch.append((n, parent))
    print(f"  编码前缀不匹配数: {len(code_mismatch)}")
    if code_mismatch:
        for n, p in code_mismatch[:10]:
            print(f"    ❌ [{n.code}] {n.name} (l{n.level[-1]}) -> parent [{p.code}] {p.name} (l{p.level[-1]})")

    # === 检查5: 每个父节点的子节点层级正确 ===
    print("\n--- 检查5: 每个父节点的子节点层级正确 ---")
    children_by_parent = {}
    for n in all_nodes:
        if n.parent_id:
            children_by_parent.setdefault(n.parent_id, []).append(n)

    bad_parent_children = []
    for pid, children in children_by_parent.items():
        parent = by_id.get(pid)
        if not parent:
            continue
        expected_child_level = f'l{level_order[parent.level] + 1}'
        for c in children:
            if c.level != expected_child_level:
                bad_parent_children.append((parent, c))
    print(f"  子节点层级错误数: {len(bad_parent_children)}")
    if bad_parent_children:
        for p, c in bad_parent_children[:10]:
            print(f"    ❌ 父 [{p.code}] {p.name} ({p.level}) -> 子 [{c.code}] {c.name} ({c.level}), 期望 {expected_child_level}")

    # === 汇总 ===
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    total_errors = len(l1_bad) + len(cross_level_errors) + len(orphans) + len(code_mismatch) + len(bad_parent_children)
    print(f"  l1 parent_id 错误: {len(l1_bad)}")
    print(f"  跨层级/孤立错误: {len(cross_level_errors)}")
    print(f"  孤立节点: {len(orphans)}")
    print(f"  编码前缀不匹配: {len(code_mismatch)}")
    print(f"  子节点层级错误: {len(bad_parent_children)}")
    print(f"  总错误数: {total_errors}")
    if total_errors == 0:
        print("\n  ✅ 父子层级关系验证全部通过！")
    else:
        print(f"\n  ❌ 发现 {total_errors} 个错误，需要修复")

finally:
    db.close()
