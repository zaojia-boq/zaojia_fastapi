"""
中建材料字典重构：
1. 修复异常编码（特殊字符）
2. 按材料名称增加中间分类层
3. 叶子节点统一层级
4. 重新生成编码
"""
import gzip, json, re, os
from collections import defaultdict, Counter

INPUT = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_cleaned.json.gz'
OUTPUT_DIR = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned'

print('加载数据...')
with gzip.open(INPUT, 'rt', encoding='utf-8') as f:
    data = json.load(f)
print(f'原始数据: {len(data):,} 条')

# ============================================================
# 第一步：修复异常编码
# ============================================================
print('\n=== 第一步：修复异常编码 ===')

def fix_code(code):
    """修复编码中的特殊字符"""
    # 移除特殊字符，保留字母数字
    fixed = re.sub(r'[^A-Za-z0-9]', '', code)
    return fixed

# 找出所有异常编码
abnormal_codes = []
code_map = {}  # 旧编码 -> 新编码
for item in data:
    if re.search(r'[^A-Za-z0-9]', item['编码']):
        abnormal_codes.append(item['编码'])

print(f'异常编码: {len(abnormal_codes)} 条')
for code in abnormal_codes:
    new_code = fix_code(code)
    code_map[code] = new_code
    print(f'  {code} -> {new_code}')

# 应用编码修复
for item in data:
    if item['编码'] in code_map:
        item['编码'] = code_map[item['编码']]
    if item.get('父编码') in code_map:
        item['父编码'] = code_map[item['父编码']]

# 检查编码唯一性
code_counter = Counter(item['编码'] for item in data)
dup_codes = {k: v for k, v in code_counter.items() if v > 1}
if dup_codes:
    print(f'警告: 修复后仍有{len(dup_codes)}个重复编码')
    for code, count in list(dup_codes.items())[:10]:
        print(f'  {code}: {count}次')
else:
    print('编码唯一性: OK')

# ============================================================
# 第二步：分析需要增加中间分类层的节点
# ============================================================
print('\n=== 第二步：分析需要增加中间分类层的节点 ===')

# 建立索引
code_index = {item['编码']: item for item in data}
children_index = defaultdict(list)
for item in data:
    parent = item.get('父编码', '')
    if parent:
        children_index[parent].append(item)

# 找出子节点有多种名称的分类节点
# 标准：子节点数量 > 5 且 名称种类 > 1
need_intermediate = []
for item in data:
    if item['层级'] < 8:  # 分类节点
        kids = children_index.get(item['编码'], [])
        if len(kids) > 5:
            kid_names = set(k['名称'] for k in kids)
            if len(kid_names) > 1:
                need_intermediate.append((item, len(kids), len(kid_names)))

print(f'需要增加中间分类层的节点: {len(need_intermediate)} 个')
for item, kid_count, name_count in need_intermediate[:20]:
    kids = children_index[item['编码']]
    kid_names = Counter(k['名称'] for k in kids)
    top_names = ', '.join([f"{n}({c})" for n, c in kid_names.most_common(3)])
    print(f"  {item['编码']} (层级{item['层级']}): {item['名称']} - {kid_count}子节点, {name_count}种名称 - {top_names}")

# ============================================================
# 第三步：执行重构 - 增加中间分类层
# ============================================================
print('\n=== 第三步：执行重构 ===')

new_data = []  # 重构后的数据
new_code_counter = {}  # 用于生成唯一编码

def generate_code(parent_code, seq):
    """生成子编码：父编码 + 序号"""
    return f"{parent_code}{seq:04d}"

def generate_intermediate_code(parent_code, seq):
    """生成中间分类编码：父编码 + 2位序号"""
    return f"{parent_code}{seq:02d}"

# 处理每个需要重构的分类节点
processed_parents = set()
intermediate_nodes = []  # 新增的中间分类节点
leaf_redirect = {}  # 旧叶子编码 -> (新父编码, 新编码)

for parent_item, kid_count, name_count in need_intermediate:
    parent_code = parent_item['编码']
    parent_level = parent_item['层级']
    kids = children_index[parent_code]

    # 按名称分组
    name_groups = defaultdict(list)
    for kid in kids:
        name_groups[kid['名称']].append(kid)

    # 为每种名称创建中间分类节点
    for seq, (name, group_kids) in enumerate(sorted(name_groups.items()), start=1):
        inter_code = generate_intermediate_code(parent_code, seq)
        inter_level = parent_level + 1

        # 检查编码冲突
        if inter_code in code_index or inter_code in new_code_counter:
            # 尝试加长序号
            inter_code = f"{parent_code}I{seq:03d}"

        inter_node = {
            '来源': group_kids[0].get('来源', ''),
            '编码': inter_code,
            '名称': name,
            '单位': '',
            '型号': '',
            '规格': '',
            '材质': '',
            '备注': f'自动分类: {len(group_kids)}个规格',
            '层级': inter_level,
            '父编码': parent_code,
            '类型': group_kids[0].get('类型', ''),
        }
        intermediate_nodes.append(inter_node)
        new_code_counter[inter_code] = True

        # 为每个叶子节点生成新编码，挂到中间分类下
        for leaf_seq, kid in enumerate(sorted(group_kids, key=lambda x: x.get('规格', '')), start=1):
            new_leaf_code = generate_code(inter_code, leaf_seq)
            leaf_redirect[kid['编码']] = (inter_code, new_leaf_code)

print(f'新增中间分类节点: {len(intermediate_nodes)} 个')
print(f'需要重新编码的叶子节点: {len(leaf_redirect)} 个')

# ============================================================
# 第四步：构建重构后的数据
# ============================================================
print('\n=== 第四步：构建重构后的数据 ===')

final_data = []

# 1. 原有分类节点（不包括被重构的叶子节点）
reconstructed_leaf_codes = set(leaf_redirect.keys())
for item in data:
    if item['编码'] not in reconstructed_leaf_codes:
        final_data.append(item)

# 2. 新增中间分类节点
final_data.extend(intermediate_nodes)

# 3. 重新编码的叶子节点
for old_code, (new_parent, new_code) in leaf_redirect.items():
    old_item = code_index[old_code]
    new_item = dict(old_item)
    new_item['编码'] = new_code
    new_item['父编码'] = new_parent
    new_item['层级'] = code_index[new_parent]['层级'] + 1 if new_parent in code_index else old_item['层级']
    final_data.append(new_item)

print(f'重构后数据: {len(final_data):,} 条')
print(f'  原有分类/叶子: {len(data) - len(reconstructed_leaf_codes):,} 条')
print(f'  新增中间分类: {len(intermediate_nodes):,} 条')
print(f'  重新编码叶子: {len(leaf_redirect):,} 条')

# ============================================================
# 第五步：统一叶子节点层级
# ============================================================
print('\n=== 第五步：统一叶子节点层级 ===')

# 重新建立索引
final_code_index = {item['编码']: item for item in final_data}
final_children = defaultdict(list)
for item in final_data:
    parent = item.get('父编码', '')
    if parent:
        final_children[parent].append(item)

# 找出所有叶子节点（没有子节点的）
leaf_nodes = [item for item in final_data if len(final_children.get(item['编码'], [])) == 0]
print(f'叶子节点总数: {len(leaf_nodes):,} 条')

# 叶子节点层级分布
leaf_levels = Counter(item['层级'] for item in leaf_nodes)
print(f'叶子节点层级分布: {dict(leaf_levels)}')

# 统一叶子节点层级为 5（5级结构）
# 但需要考虑：有些分类本身层级就比较深
# 策略：找到最大叶子层级，统一为该层级
max_leaf_level = max(leaf_levels.keys())
print(f'最大叶子层级: {max_leaf_level}')

# 不强制统一层级，保持自然层级
# 但确保所有叶子节点层级 >= 5
adjusted = 0
for item in leaf_nodes:
    if item['层级'] < 5:
        item['层级'] = 5
        adjusted += 1
print(f'调整层级<5的叶子节点: {adjusted} 条')

# ============================================================
# 第六步：验证数据完整性
# ============================================================
print('\n=== 第六步：验证数据完整性 ===')

# 编码唯一性
final_code_counter = Counter(item['编码'] for item in final_data)
final_dup = {k: v for k, v in final_code_counter.items() if v > 1}
print(f'编码唯一性: {"OK" if not final_dup else f"FAIL - {len(final_dup)}个重复"}')
if final_dup:
    for code, count in list(final_dup.items())[:10]:
        print(f'  {code}: {count}次')

# 父编码完整性
missing_parent = 0
for item in final_data:
    parent = item.get('父编码', '')
    if parent and parent not in final_code_index:
        missing_parent += 1
print(f'父编码完整性: {"OK" if missing_parent == 0 else f"FAIL - {missing_parent}个缺失"}')

# 特殊字符检查
special = [item for item in final_data if re.search(r'[^A-Za-z0-9]', item['编码'])]
print(f'特殊字符编码: {"OK" if not special else f"FAIL - {len(special)}个"}')

# 层级分布
final_levels = Counter(item['层级'] for item in final_data)
print(f'最终层级分布:')
for level in sorted(final_levels.keys()):
    print(f'  层级{level}: {final_levels[level]:,} 条')

# ============================================================
# 第七步：保存结果
# ============================================================
print('\n=== 第七步：保存结果 ===')

output_json = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v2.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(final_data, f, ensure_ascii=False, indent=2)
print(f'JSON: {output_json} ({os.path.getsize(output_json):,} bytes)')

output_gz = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v2.json.gz')
with gzip.open(output_gz, 'wt', encoding='utf-8') as f:
    json.dump(final_data, f, ensure_ascii=False)
print(f'GZIP: {output_gz} ({os.path.getsize(output_gz):,} bytes)')

# 保存重构报告
report = {
    '原始数据量': len(data),
    '重构后数据量': len(final_data),
    '新增中间分类节点': len(intermediate_nodes),
    '重新编码叶子节点': len(leaf_redirect),
    '修复异常编码': len(abnormal_codes),
    '需要重构的分类节点': len(need_intermediate),
    '叶子节点总数': len(leaf_nodes),
    '编码唯一性': 'OK' if not final_dup else 'FAIL',
    '父编码完整性': 'OK' if missing_parent == 0 else 'FAIL',
    '特殊字符编码': 'OK' if not special else 'FAIL',
    '层级分布': {str(k): v for k, v in sorted(final_levels.items())},
}
output_report = os.path.join(OUTPUT_DIR, 'reconstruction_report.json')
with open(output_report, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'报告: {output_report}')

print('\n=== 重构完成 ===')
print(f'原始: {len(data):,} 条 → 重构后: {len(final_data):,} 条 (增加 {len(final_data)-len(data):,} 个中间分类节点)')
