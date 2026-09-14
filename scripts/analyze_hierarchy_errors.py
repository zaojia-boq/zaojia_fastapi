# -*- coding: utf-8 -*-
"""分析父子层级错误的分布情况，制定修复方案。"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.material_dict import MaterialDict
from collections import defaultdict

db = SessionLocal()

try:
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                          MaterialDict.level, MaterialDict.parent_id).all()
    by_id = {n.id: n for n in all_nodes}
    level_order = {'l1': 1, 'l2': 2, 'l3': 3, 'l4': 4, 'l5': 5}

    # 分析跨层级错误
    cross_by_type = defaultdict(list)
    for n in all_nodes:
        if n.level == 'l1' or n.parent_id is None:
            continue
        parent = by_id.get(n.parent_id)
        if parent is None:
            cross_by_type['orphan'].append(n)
        elif level_order[parent.level] != level_order[n.level] - 1:
            key = f"{n.level} -> parent({parent.level})"
            cross_by_type[key].append((n, parent))

    print("=== 跨层级错误分布 ===")
    for key, items in sorted(cross_by_type.items(), key=lambda x: -len(x[1])):
        print(f"  {key}: {len(items)} 个")
        # 显示前3个示例
        for n, p in items[:3]:
            print(f"    [{n.code}] {n.name} -> [{p.code}] {p.name}")

    # 分析编码前缀不匹配
    print("\n=== 编码前缀不匹配分析 ===")
    by_code = {n.code: n for n in all_nodes if n.code}
    prefix_mismatch = []
    for n in all_nodes:
        if not n.code or n.level == 'l1' or n.parent_id is None:
            continue
        parent = by_id.get(n.parent_id)
        if parent and parent.code and not n.code.startswith(parent.code):
            prefix_mismatch.append((n, parent))
    print(f"  编码前缀不匹配: {len(prefix_mismatch)} 个")
    for n, p in prefix_mismatch[:5]:
        print(f"    [{n.code}] {n.name} ({n.level}) -> [{p.code}] {p.name} ({p.level})")

    # 检查：这些错误节点是否有子节点（修复时需要考虑级联影响）
    print("\n=== 错误节点的子节点情况 ===")
    children_by_parent = defaultdict(list)
    for n in all_nodes:
        if n.parent_id:
            children_by_parent[n.parent_id].append(n)

    error_node_ids = set()
    for items in cross_by_type.values():
        for item in items:
            if isinstance(item, tuple):
                error_node_ids.add(item[0].id)
            else:
                error_node_ids.add(item.id)
    for n, p in prefix_mismatch:
        error_node_ids.add(n.id)

    nodes_with_children = [nid for nid in error_node_ids if children_by_parent.get(nid)]
    print(f"  错误节点总数: {len(error_node_ids)}")
    print(f"  其中有子节点的: {len(nodes_with_children)}")

    # 按层级统计错误节点
    print("\n=== 错误节点按层级统计 ===")
    error_by_level = defaultdict(int)
    for nid in error_node_ids:
        n = by_id.get(nid)
        if n:
            error_by_level[n.level] += 1
    for lv in ['l1', 'l2', 'l3', 'l4', 'l5']:
        print(f"  {lv}: {error_by_level.get(lv, 0)} 个")

finally:
    db.close()
