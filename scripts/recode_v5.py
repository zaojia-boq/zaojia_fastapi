"""
重新编码：3-2-2-3-4 方案
- 第一层（根）：3位 (001-999)
- 第二层：2位 (01-99)
- 第三层：2位 (01-99)
- 第四层（材料名称）：3位 (001-999)
- 第五层（规格）：4位 (0001-9999)

总长度：1(I) + 3 + 2 + 2 + 3 + 4 = 15位
示例：I00101010010001
"""
import gzip, json, os
from collections import defaultdict

INPUT = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v4.json.gz'
OUTPUT_DIR = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned'

print('加载数据...')
with gzip.open(INPUT, 'rt', encoding='utf-8') as f:
    data = json.load(f)
print(f'原始数据: {len(data):,} 条')

# 建立索引
old_code_index = {item['编码']: item for item in data}
old_children = defaultdict(list)
for item in data:
    parent = item.get('父编码', '')
    if parent:
        old_children[parent].append(item)

# 新旧编码映射
code_map = {}  # 旧编码 -> 新编码

def gen_code(prefix, seq, width):
    """生成编码：前缀 + 序号（指定宽度）"""
    return f"{prefix}{seq:0{width}d}"

def recode_node(old_code, parent_new_code, level):
    """
    递归重新编码节点
    level: 1-5
    返回该节点的新编码
    """
    old_item = old_code_index[old_code]

    # 确定当前层的编码宽度
    widths = {1: 3, 2: 2, 3: 2, 4: 3, 5: 4}
    width = widths.get(level, 4)

    # 生成新编码（需要知道在兄弟节点中的序号）
    # 由调用方传入序号
    pass

# 按层级处理
# 第一层：根节点
print('\n重新编码...')
level1_nodes = [item for item in data if item['层级'] == 1]
level1_nodes.sort(key=lambda x: x['编码'])

for i, item in enumerate(level1_nodes, start=1):
    new_code = gen_code('I', i, 3)
    code_map[item['编码']] = new_code

print(f'  第一层: {len(level1_nodes)} 个根节点')

# 第二层
level2_count = 0
for old_l1_code in [item['编码'] for item in level1_nodes]:
    new_l1_code = code_map[old_l1_code]
    children = old_children.get(old_l1_code, [])
    children.sort(key=lambda x: x['编码'])
    for i, child in enumerate(children, start=1):
        new_code = gen_code(new_l1_code, i, 2)
        code_map[child['编码']] = new_code
        level2_count += 1
print(f'  第二层: {level2_count} 个')

# 第三层
level3_count = 0
level2_nodes = [item for item in data if item['层级'] == 2]
for item in level2_nodes:
    old_l2_code = item['编码']
    new_l2_code = code_map[old_l2_code]
    children = old_children.get(old_l2_code, [])
    children.sort(key=lambda x: x['编码'])
    for i, child in enumerate(children, start=1):
        new_code = gen_code(new_l2_code, i, 2)
        code_map[child['编码']] = new_code
        level3_count += 1
print(f'  第三层: {level3_count} 个')

# 第四层（材料名称）
level4_count = 0
level3_nodes = [item for item in data if item['层级'] == 3]
for item in level3_nodes:
    old_l3_code = item['编码']
    new_l3_code = code_map[old_l3_code]
    children = old_children.get(old_l3_code, [])
    children.sort(key=lambda x: x['编码'])
    for i, child in enumerate(children, start=1):
        new_code = gen_code(new_l3_code, i, 3)
        code_map[child['编码']] = new_code
        level4_count += 1
print(f'  第四层: {level4_count} 个')

# 第五层（规格叶子）
level5_count = 0
level4_nodes = [item for item in data if item['层级'] == 4]
for item in level4_nodes:
    old_l4_code = item['编码']
    new_l4_code = code_map[old_l4_code]
    children = old_children.get(old_l4_code, [])
    children.sort(key=lambda x: x.get('规格', ''))
    for i, child in enumerate(children, start=1):
        new_code = gen_code(new_l4_code, i, 4)
        code_map[child['编码']] = new_code
        level5_count += 1
print(f'  第五层: {level5_count} 个')

# 验证所有编码都已映射
unmapped = [item['编码'] for item in data if item['编码'] not in code_map]
print(f'\n未映射编码: {len(unmapped)} 个')
if unmapped:
    for code in unmapped[:10]:
        print(f'  {code}: {old_code_index[code]["名称"]} (层级{old_code_index[code]["层级"]})')

# 应用新编码
new_data = []
for item in data:
    new_item = dict(item)
    old_code = item['编码']
    old_parent = item.get('父编码', '')

    if old_code in code_map:
        new_item['编码'] = code_map[old_code]
    if old_parent and old_parent in code_map:
        new_item['父编码'] = code_map[old_parent]

    new_data.append(new_item)

# 验证编码唯一性
new_codes = [item['编码'] for item in new_data]
print(f'\n新编码唯一性: {"OK" if len(new_codes) == len(set(new_codes)) else "FAIL"}')
print(f'新编码总数: {len(new_codes):,}')

# 验证编码长度
code_lengths = set(len(code) for code in new_codes)
print(f'编码长度分布: {sorted(code_lengths)}')

# 显示示例
print('\n编码示例:')
examples = [
    ('I001', '第一层（根）'),
]
# 找几个实际示例
for item in new_data[:5]:
    print(f'  {item["编码"]} (层级{item["层级"]}, 长度{len(item["编码"])}): {item["名称"]}')

# 找圆钢Q235的示例
for item in new_data:
    if item['名称'] == '圆钢(Q235)' and item['层级'] == 4:
        print(f'\n圆钢(Q235)材料名称: {item["编码"]} (长度{len(item["编码"])})')
        children = [c for c in new_data if c.get('父编码') == item['编码']]
        for child in children[:3]:
            print(f'  {child["编码"]}: {child["名称"]} | 规格:{child.get("规格","无")}')
        break

# 保存
print('\n保存...')
output_json = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v5.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False, indent=2)
print(f'JSON: {output_json} ({os.path.getsize(output_json):,} bytes)')

output_gz = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_v5.json.gz')
with gzip.open(output_gz, 'wt', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False)
print(f'GZIP: {output_gz} ({os.path.getsize(output_gz):,} bytes)')

# 保存编码映射
output_map = os.path.join(OUTPUT_DIR, 'code_mapping_v5.json')
with open(output_map, 'w', encoding='utf-8') as f:
    json.dump(code_map, f, ensure_ascii=False, indent=2)
print(f'编码映射: {output_map} ({len(code_map):,} 条映射)')

print(f'\n=== 重新编码完成 ===')
print(f'编码方案: 3-2-2-3-4 (总长度15位)')
print(f'示例: I00101010010001')
print(f'  I=前缀, 001=第一层, 01=第二层, 01=第三层, 001=第四层, 0001=第五层')
