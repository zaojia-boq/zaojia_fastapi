# -*- coding: utf-8 -*-
"""分析剩余跨层级错误的编码长度分布和层级关系。"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.material_dict import MaterialDict
from collections import Counter, defaultdict

db = SessionLocal()
try:
    all_nodes = db.query(MaterialDict.id, MaterialDict.name, MaterialDict.code,
                          MaterialDict.level, MaterialDict.parent_id).all()
    by_id = {n.id: n for n in all_nodes}

    # 找出跨层级错误
    errors = []
    for n in all_nodes:
        if n.level == 'l1' or n.parent_id is None:
            continue
        parent = by_id.get(n.parent_id)
        if parent is None or int(parent.level[1]) != int(n.level[1]) - 1:
            errors.append((n, parent))

    print(f"跨层级错误总数: {len(errors)}")

    # 按错误节点的编码长度分布
    code_lens = Counter()
    code_len_examples = defaultdict(list)
    for n, p in errors:
        if n.code:
            l = len(n.code)
            code_lens[l] += 1
            if len(code_len_examples[l]) < 5:
                pname = p.name if p else 'NOT FOUND'
                code_len_examples[l].append(f"{n.code} {n.name} ({n.level}) -> 父: {pname} ({p.level if p else '?'})")

    print("\n=== 错误节点编码长度分布 ===")
    for l in sorted(code_lens.keys()):
        print(f"  {l}字符: {code_lens[l]}条")
        for ex in code_len_examples[l]:
            print(f"    {ex}")

    # 按错误节点的层级分布
    levels = Counter(n.level for n, p in errors)
    print("\n=== 错误节点层级分布 ===")
    for lv in sorted(levels.keys()):
        print(f"  {lv}: {levels[lv]}条")

    # 按父节点的层级分布
    parent_levels = Counter(p.level if p else 'None' for n, p in errors)
    print("\n=== 父节点层级分布 ===")
    for lv in sorted(parent_levels.keys()):
        print(f"  {lv}: {parent_levels[lv]}条")

    # 分析：错误节点的编码长度与层级的对应关系
    print("\n=== 错误节点：编码长度 vs 层级标记 ===")
    len_level = defaultdict(Counter)
    for n, p in errors:
        if n.code:
            len_level[len(n.code)][n.level] += 1
    for l in sorted(len_level.keys()):
        print(f"  {l}字符: {dict(len_level[l])}")

finally:
    db.close()
