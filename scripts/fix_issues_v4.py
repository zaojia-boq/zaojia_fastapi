"""
修复材料字典问题：
1. 修复粘土砖下红砖的单位（卷→块）
2. 合并重复的红砖（保留页岩砖下的，删除粘土砖下的）
3. 修复其他明显单位错误
4. 输出修复报告
"""
import gzip, json, os
from collections import defaultdict, Counter

INPUT = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v3.json.gz'
OUTPUT_DIR = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned'

print('加载数据...')
with gzip.open(INPUT, 'rt', encoding='utf-8') as f:
    data = json.load(f)
print(f'原始数据: {len(data):,} 条')

code_index = {item['编码']: item for item in data}
children = defaultdict(list)
for item in data:
    parent = item.get('父编码', '')
    if parent:
        children[parent].append(item)

fixes = []
deletions = []

# ============================================================
# 1. 查找并修复粘土砖下的红砖
# ============================================================
print('\n=== 1. 修复红砖问题 ===')

# 找粘土砖下的红砖（层级4材料名称节点和层级5叶子节点）
clay_brick_mat = None
clay_brick_leaf = None
shale_brick_mat = None
shale_brick_leaf = None

for item in data:
    if item['名称'] == '红砖' and item['层级'] == 4:
        path_parent = item.get('父编码', '')
        if path_parent in code_index:
            parent_name = code_index[path_parent]['名称']
            if '粘土砖' in parent_name:
                clay_brick_mat = item
            elif '页岩砖' in parent_name:
                shale_brick_mat = item
    elif item['名称'] == '红砖' and item['层级'] == 5:
        path_parent = item.get('父编码', '')
        if path_parent in code_index:
            grandparent = code_index[path_parent].get('父编码', '')
            if grandparent in code_index:
                grandparent_name = code_index[grandparent]['名称']
                if '粘土砖' in grandparent_name:
                    clay_brick_leaf = item
                elif '页岩砖' in grandparent_name:
                    shale_brick_leaf = item

if clay_brick_leaf:
    print(f'粘土砖下红砖叶子: {clay_brick_leaf["编码"]} | 单位:{clay_brick_leaf.get("单位","无")} | 规格:{clay_brick_leaf.get("规格","无")}')
if shale_brick_leaf:
    print(f'页岩砖下红砖叶子: {shale_brick_leaf["编码"]} | 单位:{shale_brick_leaf.get("单位","无")} | 规格:{shale_brick_leaf.get("规格","无")}')

# 修复策略：
# - 粘土砖下的红砖单位错误（卷→块），但规格为空
# - 页岩砖下的红砖单位正确（块），有规格
# - 两者是重复的，保留页岩砖下的（信息更完整），删除粘土砖下的
# - 同时删除粘土砖下的红砖材料名称节点（层级4），因为没有子节点了

if clay_brick_leaf and shale_brick_leaf:
    # 删除粘土砖下的红砖叶子
    deletions.append({
        '编码': clay_brick_leaf['编码'],
        '名称': clay_brick_leaf['名称'],
        '原因': '与页岩砖下红砖重复，保留信息更完整的页岩砖版本',
        '原单位': clay_brick_leaf.get('单位', ''),
        '原规格': clay_brick_leaf.get('规格', ''),
    })
    data = [item for item in data if item['编码'] != clay_brick_leaf['编码']]

    # 删除粘土砖下的红砖材料名称节点（如果没有其他子节点）
    if clay_brick_mat:
        remaining_children = [item for item in data if item.get('父编码') == clay_brick_mat['编码']]
        if len(remaining_children) == 0:
            deletions.append({
                '编码': clay_brick_mat['编码'],
                '名称': clay_brick_mat['名称'],
                '原因': '材料名称节点无剩余子节点，随重复叶子一起删除',
            })
            data = [item for item in data if item['编码'] != clay_brick_mat['编码']]
        else:
            print(f'  警告: 粘土砖下红砖材料名称节点仍有{len(remaining_children)}个子节点，不删除')

    print(f'  已删除粘土砖下红砖（重复），保留页岩砖下红砖')
    fixes.append('修复红砖重复：删除粘土砖下重复红砖，保留页岩砖下版本（单位:块，规格:120*240*6mm）')

# ============================================================
# 2. 修复其他明显单位错误
# ============================================================
print('\n=== 2. 修复其他明显单位错误 ===')

# 单位错误映射：根据材料名称判断合理单位
unit_fixes = [
    # (名称关键词, 错误单位, 正确单位, 说明)
    ('红砖', '卷', '块', '砖类材料单位应为块'),
    ('页岩砖', '匹', '块', '砖类材料单位应为块'),
    ('异型砖', '台', '块', '砖类材料单位应为块'),
]

for keyword, wrong_unit, correct_unit, reason in unit_fixes:
    for item in data:
        if keyword in item.get('名称', '') and item.get('单位') == wrong_unit:
            old_unit = item['单位']
            item['单位'] = correct_unit
            fixes.append(f'修复单位：{item["编码"]} {item["名称"]} {old_unit}→{correct_unit}（{reason}）')
            print(f'  {item["编码"]}: {item["名称"]} {old_unit}→{correct_unit}')

# ============================================================
# 3. 排查砖类材料单位异常（输出报告，不自动修复）
# ============================================================
print('\n=== 3. 砖类材料单位异常排查（仅报告） ===')
brick_items = [item for item in data if '砖' in item.get('名称', '') and item['层级'] == 5]
brick_units = Counter(item.get('单位', '') for item in brick_items)
print(f'砖类材料单位分布:')
for unit, count in brick_units.most_common():
    status = '✅' if unit in ['块', '千块', '立方米', '平方米', '吨', ''] else '⚠️'
    print(f'  {status} {unit or "无"}: {count} 条')

# 输出单位异常的砖类材料
abnormal_bricks = []
for item in brick_items:
    unit = item.get('单位', '')
    if unit and unit not in ['块', '千块', '立方米', '平方米', '吨']:
        abnormal_bricks.append(item)

print(f'\n单位异常的砖类材料: {len(abnormal_bricks)} 条')
for item in abnormal_bricks[:20]:
    path = []
    current = item
    while current:
        path.insert(0, current['名称'])
        parent = current.get('父编码', '')
        current = code_index.get(parent) if parent else None
    print(f'  {item["编码"]}: {item["名称"]} | 单位:{item.get("单位","无")} | 规格:{item.get("规格","无")}')
    print(f'    路径: {" → ".join(path[-4:])}')

# ============================================================
# 4. 跨分类重复名称排查（输出报告，不自动修复）
# ============================================================
print('\n=== 4. 跨分类重复名称排查（仅报告） ===')

# 重新建立索引（因为删除了一些记录）
code_index = {item['编码']: item for item in data}

name_by_parent = defaultdict(set)
for item in data:
    if item['层级'] == 5:
        name_by_parent[item['名称']].add(item.get('父编码', ''))

cross_category = {name: parents for name, parents in name_by_parent.items() if len(parents) > 1}
print(f'在多个分类下出现的材料名称: {len(cross_category)} 个')

# 分析这些是否真的重复（规格/单位是否相同）
true_duplicates = []
for name, parents in cross_category.items():
    items = [item for item in data if item['名称'] == name and item['层级'] == 5]
    # 按规格+单位分组
    spec_groups = defaultdict(list)
    for item in items:
        key = (item.get('规格', ''), item.get('单位', ''))
        spec_groups[key].append(item)
    # 找出规格+单位完全相同的
    for key, group in spec_groups.items():
        if len(group) > 1 and key[0]:  # 有规格且重复
            true_duplicates.append((name, key, group))

print(f'其中规格+单位完全相同的真重复: {len(true_duplicates)} 组')
print('\n前20组真重复:')
for name, (spec, unit), group in true_duplicates[:20]:
    paths = []
    for item in group:
        path = []
        current = item
        while current:
            path.insert(0, current['名称'])
            parent = current.get('父编码', '')
            current = code_index.get(parent) if parent else None
        paths.append(' → '.join(path[-3:]))
    print(f'  {name} | 规格:{spec} | 单位:{unit} | {len(group)}条')
    for p in paths:
        print(f'    - {p}')

# ============================================================
# 5. 保存修复后的数据
# ============================================================
print('\n=== 5. 保存修复后的数据 ===')

output_json = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v4.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f'JSON: {output_json} ({os.path.getsize(output_json):,} bytes)')

output_gz = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v4.json.gz')
with gzip.open(output_gz, 'wt', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print(f'GZIP: {output_gz} ({os.path.getsize(output_gz):,} bytes)')

# 保存修复报告
report = {
    '原始数据量': len(data) + len(deletions),
    '修复后数据量': len(data),
    '删除记录数': len(deletions),
    '修复项数': len(fixes),
    '删除记录': deletions,
    '修复项': fixes,
    '砖类单位异常数': len(abnormal_bricks),
    '跨分类重复名称数': len(cross_category),
    '真重复组数': len(true_duplicates),
}
output_report = os.path.join(OUTPUT_DIR, 'fix_report_v4.json')
with open(output_report, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'报告: {output_report}')

print(f'\n=== 修复完成 ===')
print(f'原始: {len(data) + len(deletions):,} 条 → 修复后: {len(data):,} 条')
print(f'删除: {len(deletions)} 条，修复: {len(fixes)} 项')
print(f'待人工确认: 砖类单位异常{len(abnormal_bricks)}条，真重复{len(true_duplicates)}组')
