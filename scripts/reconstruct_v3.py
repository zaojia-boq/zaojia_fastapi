"""
中建材料字典重构 v2：
- 5级结构：根(1)→大类(2)→中类(3)→材料名称(4)→规格叶子(5)
- 所有叶子节点统一层级5
- 编码唯一，父编码完整
- 修复异常编码
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
# 第一步：修复异常编码（移除特殊字符）
# ============================================================
print('\n=== 第一步：修复异常编码 ===')

def fix_code(code):
    return re.sub(r'[^A-Za-z0-9]', '', code)

code_map = {}
for item in data:
    if re.search(r'[^A-Za-z0-9]', item['编码']):
        old = item['编码']
        new = fix_code(old)
        # 处理冲突
        base = new
        seq = 1
        while new in [i['编码'] for i in data if i['编码'] != old] or new in code_map.values():
            new = f"{base}{seq}"
            seq += 1
        code_map[old] = new

print(f'修复异常编码: {len(code_map)} 条')

for item in data:
    if item['编码'] in code_map:
        item['编码'] = code_map[item['编码']]
    if item.get('父编码') in code_map:
        item['父编码'] = code_map[item['父编码']]

# ============================================================
# 第二步：建立树结构，找出所有叶子节点
# ============================================================
print('\n=== 第二步：建立树结构 ===')

code_index = {item['编码']: item for item in data}
children_index = defaultdict(list)
for item in data:
    parent = item.get('父编码', '')
    if parent and parent in code_index:
        children_index[parent].append(item)

# 叶子节点 = 没有子节点的节点
leaf_codes = set()
for item in data:
    if len(children_index.get(item['编码'], [])) == 0:
        leaf_codes.add(item['编码'])

print(f'叶子节点: {len(leaf_codes):,} 条')
print(f'分类节点: {len(data) - len(leaf_codes):,} 条')

# ============================================================
# 第三步：为每个叶子节点找到4级路径
# 规则：
#   层级1 = 根节点（父编码为空）
#   层级2 = 根的直接子节点
#   层级3 = 材料类别（如圆钢、角钢）
#   层级4 = 材料名称（如圆钢Q235、镀锌圆钢）
#   层级5 = 规格叶子
#
# 策略：
#   1. 从根到叶子的路径，如果路径长度 < 5，在叶子前插入材料名称层
#   2. 如果路径长度 > 5，压缩中间层
#   3. 材料名称层 = 叶子节点的名称（相同名称的叶子聚类到同一材料名称节点下）
# ============================================================
print('\n=== 第三步：构建5级路径 ===')

def get_path(code):
    """获取从根到节点的路径"""
    path = []
    current = code_index.get(code)
    while current:
        path.insert(0, current)
        parent = current.get('父编码', '')
        if parent and parent in code_index:
            current = code_index[parent]
        else:
            current = None
    return path

# 为每个叶子节点构建路径
leaf_paths = {}
for code in leaf_codes:
    path = get_path(code)
    leaf_paths[code] = path

# 分析路径长度分布
path_lengths = Counter(len(p) for p in leaf_paths.values())
print(f'叶子路径长度分布: {dict(path_lengths)}')

# ============================================================
# 第四步：生成新的5级结构
# ============================================================
print('\n=== 第四步：生成5级结构 ===')

new_data = []
new_code_index = {}
new_children = defaultdict(list)

# 编码生成器
code_counters = defaultdict(int)

def gen_code(parent_code):
    """生成子编码：父编码 + 4位序号"""
    code_counters[parent_code] += 1
    return f"{parent_code}{code_counters[parent_code]:04d}"

def add_node(source_item, level, parent_code, name_override=None):
    """添加新节点"""
    code = gen_code(parent_code)
    node = {
        '来源': source_item.get('来源', ''),
        '编码': code,
        '名称': name_override or source_item['名称'],
        '单位': source_item.get('单位', ''),
        '型号': source_item.get('型号', ''),
        '规格': source_item.get('规格', ''),
        '材质': source_item.get('材质', ''),
        '备注': source_item.get('备注', ''),
        '层级': level,
        '父编码': parent_code,
        '类型': source_item.get('类型', ''),
    }
    new_data.append(node)
    new_code_index[code] = node
    new_children[parent_code].append(node)
    return code

# 处理根节点（层级1）
root_nodes = [item for item in data if not item.get('父编码') or item['父编码'] not in code_index]
print(f'根节点: {len(root_nodes)} 个')

root_code_map = {}  # 旧根编码 -> 新根编码
for root in root_nodes:
    new_code = f"I{len(root_code_map)+1:03d}"
    node = {
        '来源': root.get('来源', ''),
        '编码': new_code,
        '名称': root['名称'],
        '单位': '', '型号': '', '规格': '', '材质': '', '备注': '',
        '层级': 1,
        '父编码': '',
        '类型': root.get('类型', ''),
    }
    new_data.append(node)
    new_code_index[new_code] = node
    root_code_map[root['编码']] = new_code

print(f'根节点编码映射: {len(root_code_map)} 个')

# 递归处理每个根节点下的子树
# 策略：遍历原树，将每个节点映射到新的层级1-4
# 叶子节点统一层级5，相同名称的叶子聚类到同一材料名称节点（层级4）下

material_name_cache = {}  # (父新编码, 材料名称) -> 新编码

def process_subtree(old_parent_code, new_parent_code, target_level):
    """
    处理子树，将原树节点映射到新层级
    target_level: 当前目标层级（2-4）
    """
    old_children = children_index.get(old_parent_code, [])

    for old_child in old_children:
        old_code = old_child['编码']

        # 判断这个子节点是否是叶子
        is_leaf = old_code in leaf_codes

        if is_leaf:
            # 叶子节点：需要先创建/找到材料名称节点（层级4），然后挂叶子
            material_name = old_child['名称']
            cache_key = (new_parent_code, material_name)

            if cache_key in material_name_cache:
                # 已存在材料名称节点
                mat_code = material_name_cache[cache_key]
            else:
                # 创建材料名称节点（层级4）
                mat_code = gen_code(new_parent_code)
                mat_node = {
                    '来源': old_child.get('来源', ''),
                    '编码': mat_code,
                    '名称': material_name,
                    '单位': '', '型号': '', '规格': '', '材质': '',
                    '备注': f'材料名称分类（自动生成）',
                    '层级': 4,
                    '父编码': new_parent_code,
                    '类型': old_child.get('类型', ''),
                }
                new_data.append(mat_node)
                new_code_index[mat_code] = mat_node
                new_children[new_parent_code].append(mat_node)
                material_name_cache[cache_key] = mat_code

            # 创建叶子节点（层级5）
            leaf_code = gen_code(mat_code)
            leaf_node = {
                '来源': old_child.get('来源', ''),
                '编码': leaf_code,
                '名称': material_name,
                '单位': old_child.get('单位', ''),
                '型号': old_child.get('型号', ''),
                '规格': old_child.get('规格', ''),
                '材质': old_child.get('材质', ''),
                '备注': old_child.get('备注', ''),
                '层级': 5,
                '父编码': mat_code,
                '类型': old_child.get('类型', ''),
            }
            new_data.append(leaf_node)
            new_code_index[leaf_code] = leaf_node
            new_children[mat_code].append(leaf_node)

        else:
            # 分类节点：映射到目标层级
            if target_level <= 4:
                new_code = gen_code(new_parent_code)
                node = {
                    '来源': old_child.get('来源', ''),
                    '编码': new_code,
                    '名称': old_child['名称'],
                    '单位': '', '型号': '', '规格': '', '材质': '',
                    '备注': old_child.get('备注', ''),
                    '层级': target_level,
                    '父编码': new_parent_code,
                    '类型': old_child.get('类型', ''),
                }
                new_data.append(node)
                new_code_index[new_code] = node
                new_children[new_parent_code].append(node)

                # 递归处理子节点，层级+1
                # 如果已经到层级4，子节点应该是叶子（直接挂到层级4下，创建层级5叶子）
                if target_level < 4:
                    process_subtree(old_code, new_code, target_level + 1)
                else:
                    # 已经到层级4，子节点直接作为叶子处理
                    # 但需要按名称聚类到材料名称节点
                    grand_children = children_index.get(old_code, [])
                    for gc in grand_children:
                        if gc['编码'] in leaf_codes:
                            material_name = gc['名称']
                            cache_key = (new_code, material_name)
                            if cache_key in material_name_cache:
                                mat_code = material_name_cache[cache_key]
                            else:
                                mat_code = gen_code(new_code)
                                mat_node = {
                                    '来源': gc.get('来源', ''),
                                    '编码': mat_code,
                                    '名称': material_name,
                                    '单位': '', '型号': '', '规格': '', '材质': '',
                                    '备注': '材料名称分类（自动生成）',
                                    '层级': 4,
                                    '父编码': new_code,
                                    '类型': gc.get('类型', ''),
                                }
                                new_data.append(mat_node)
                                new_code_index[mat_code] = mat_node
                                material_name_cache[cache_key] = mat_code

                            leaf_code = gen_code(mat_code)
                            leaf_node = {
                                '来源': gc.get('来源', ''),
                                '编码': leaf_code,
                                '名称': material_name,
                                '单位': gc.get('单位', ''),
                                '型号': gc.get('型号', ''),
                                '规格': gc.get('规格', ''),
                                '材质': gc.get('材质', ''),
                                '备注': gc.get('备注', ''),
                                '层级': 5,
                                '父编码': mat_code,
                                '类型': gc.get('类型', ''),
                            }
                            new_data.append(leaf_node)
                            new_code_index[leaf_code] = leaf_node

# 处理每个根节点
for old_root in root_nodes:
    new_root_code = root_code_map[old_root['编码']]
    process_subtree(old_root['编码'], new_root_code, 2)

print(f'重构后数据: {len(new_data):,} 条')

# ============================================================
# 第五步：验证
# ============================================================
print('\n=== 第五步：验证 ===')

# 编码唯一性
code_counter = Counter(item['编码'] for item in new_data)
dup_codes = {k: v for k, v in code_counter.items() if v > 1}
print(f'编码唯一性: {"OK" if not dup_codes else f"FAIL - {len(dup_codes)}个重复"}')
if dup_codes:
    for code, count in list(dup_codes.items())[:10]:
        print(f'  {code}: {count}次')

# 父编码完整性
missing_parent = 0
for item in new_data:
    parent = item.get('父编码', '')
    if parent and parent not in new_code_index:
        missing_parent += 1
print(f'父编码完整性: {"OK" if missing_parent == 0 else f"FAIL - {missing_parent}个缺失"}')

# 层级分布
level_counter = Counter(item['层级'] for item in new_data)
print(f'层级分布:')
for level in sorted(level_counter.keys()):
    print(f'  层级{level}: {level_counter[level]:,} 条')

# 叶子节点层级
new_leaf_codes = set()
for item in new_data:
    if len(new_children.get(item['编码'], [])) == 0:
        new_leaf_codes.add(item['编码'])
new_leaf_levels = Counter(item['层级'] for item in new_data if item['编码'] in new_leaf_codes)
print(f'叶子节点层级分布: {dict(new_leaf_levels)}')
print(f'叶子节点总数: {len(new_leaf_codes):,}')

# 特殊字符检查
special = [item for item in new_data if re.search(r'[^A-Za-z0-9]', item['编码'])]
print(f'特殊字符编码: {"OK" if not special else f"FAIL - {len(special)}个"}')

# ============================================================
# 第六步：保存
# ============================================================
print('\n=== 第六步：保存 ===')

output_json = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v3.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False, indent=2)
print(f'JSON: {output_json} ({os.path.getsize(output_json):,} bytes)')

output_gz = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v3.json.gz')
with gzip.open(output_gz, 'wt', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False)
print(f'GZIP: {output_gz} ({os.path.getsize(output_gz):,} bytes)')

report = {
    '原始数据量': len(data),
    '重构后数据量': len(new_data),
    '根节点': len(root_nodes),
    '叶子节点': len(new_leaf_codes),
    '编码唯一性': 'OK' if not dup_codes else 'FAIL',
    '父编码完整性': 'OK' if missing_parent == 0 else 'FAIL',
    '层级分布': {str(k): v for k, v in sorted(level_counter.items())},
    '叶子节点层级': {str(k): v for k, v in sorted(new_leaf_levels.items())},
}
output_report = os.path.join(OUTPUT_DIR, 'reconstruction_report_v3.json')
with open(output_report, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'报告: {output_report}')

print('\n=== 重构完成 ===')
print(f'5级结构：根(1)→大类(2)→中类(3)→材料名称(4)→规格叶子(5)')
print(f'原始: {len(data):,} 条 → 重构后: {len(new_data):,} 条')
