# -*- coding: utf-8 -*-
"""分析v5数据的编码长度分布，确定完整的编码层级映射。"""
import gzip
import json
from collections import Counter, defaultdict

v5_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'

with gzip.open(v5_path, 'rt', encoding='utf-8') as f:
    data = json.load(f)

print(f"v5数据总条数: {len(data)}")

# 编码长度分布
code_lens = Counter()
code_len_examples = defaultdict(list)
for item in data:
    code = item.get('编码', '')
    if code:
        l = len(code)
        code_lens[l] += 1
        if len(code_len_examples[l]) < 3:
            code_len_examples[l].append(f"{code} {item.get('名称','')} (层级={item.get('层级','')})")

print("\n=== 编码长度分布 ===")
for l in sorted(code_lens.keys()):
    print(f"  {l}字符: {code_lens[l]}条")
    for ex in code_len_examples[l]:
        print(f"    例: {ex}")

# 层级标记分布
levels = Counter(item.get('层级', '') for item in data)
print("\n=== 层级标记分布 ===")
for lv in sorted(levels.keys()):
    print(f"  {lv}: {levels[lv]}条")

# 分析：每个层级标记对应的编码长度
level_code_lens = defaultdict(Counter)
for item in data:
    lv = item.get('层级', '')
    code = item.get('编码', '')
    if code:
        level_code_lens[lv][len(code)] += 1

print("\n=== 各层级标记对应的编码长度 ===")
for lv in sorted(level_code_lens.keys()):
    print(f"  {lv}:")
    for l, cnt in level_code_lens[lv].most_common():
        print(f"    {l}字符: {cnt}条")

# 分析编码前缀与父编码的关系
print("\n=== 编码前缀层级关系分析（抽样）===")
by_code = {item['编码']: item for item in data if item.get('编码')}
for item in data[:20]:
    code = item.get('编码', '')
    parent_code = item.get('父编码', '')
    if code and parent_code:
        print(f"  {code}({len(code)}字符, {item.get('层级','')}) -> 父: {parent_code}({len(parent_code)}字符)")
