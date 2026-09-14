"""
中建材料字典数据清洗与同类项合并
清洗规则：
1. 名称：全角括号→半角括号，去除不可见字符
2. 规格：φ→Φ，x→×（乘号），去除前后空格
3. 单位：平米→平方米，统一同义单位
4. 层级：重新分配连续层级（1-5级）
5. 合并：清洗后相同 名称+规格+型号+单位 的叶子节点合并
"""
import gzip, json, re, os
from collections import Counter, defaultdict

INPUT = r'E:\DEEPSEEK学习\_test_data\中建材料字典_网页版\zhongjian_material_dict.json.gz'
OUTPUT_DIR = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 加载数据
print('加载数据...')
with gzip.open(INPUT, 'rt', encoding='utf-8') as f:
    data = json.load(f)
print(f'原始数据: {len(data):,} 条')

# ============================================================
# 清洗函数
# ============================================================
def clean_name(name):
    """清洗名称：全角括号→半角，去除不可见字符"""
    if not name:
        return name
    name = name.strip()
    name = name.replace('（', '(').replace('）', ')')
    name = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name)
    return name

def clean_spec(spec):
    """清洗规格：φ→Φ，x→×（乘号场景），去除前后空格"""
    if not spec:
        return spec
    spec = spec.strip()
    spec = spec.replace('φ', 'Φ')  # 小写phi→大写Phi
    # x 乘号统一：数字x数字 → 数字×数字
    spec = re.sub(r'(\d)\s*[xX]\s*(\d)', r'\1×\2', spec)
    return spec

def clean_unit(unit):
    """清洗单位：统一同义单位"""
    if not unit:
        return unit
    unit = unit.strip()
    unit_map = {
        '平米': '平方米',
        '平方': '平方米',
        '㎡': '平方米',
        'm2': '平方米',
        '立方': '立方米',
        'm3': '立方米',
        '㎥': '立方米',
        '公斤': '千克',
        'kg': '千克',
        'KM': '千米',
        'km': '千米',
        '公分': '厘米',
        'cm': '厘米',
        '公厘': '毫米',
        'mm': '毫米',
    }
    return unit_map.get(unit, unit)

def clean_model(model):
    """清洗型号"""
    if not model:
        return model
    return model.strip()

def clean_material(material):
    """清洗材质"""
    if not material:
        return material
    return material.strip()

def clean_remark(remark):
    """清洗备注"""
    if not remark:
        return remark
    return remark.strip()

# ============================================================
# 执行清洗
# ============================================================
print('\n执行清洗...')
cleaned = []
stats = {'name': 0, 'spec': 0, 'unit': 0, 'model': 0}

for item in data:
    new_item = dict(item)
    old_name = item.get('名称', '')
    new_name = clean_name(old_name)
    if new_name != old_name:
        stats['name'] += 1
    new_item['名称'] = new_name

    old_spec = item.get('规格', '')
    new_spec = clean_spec(old_spec)
    if new_spec != old_spec:
        stats['spec'] += 1
    new_item['规格'] = new_spec

    old_unit = item.get('单位', '')
    new_unit = clean_unit(old_unit)
    if new_unit != old_unit:
        stats['unit'] += 1
    new_item['单位'] = new_unit

    old_model = item.get('型号', '')
    new_model = clean_model(old_model)
    if new_model != old_model:
        stats['model'] += 1
    new_item['型号'] = new_model

    new_item['材质'] = clean_material(item.get('材质', ''))
    new_item['备注'] = clean_remark(item.get('备注', ''))

    cleaned.append(new_item)

print(f'  名称清洗: {stats["name"]:,} 条')
print(f'  规格清洗: {stats["spec"]:,} 条')
print(f'  单位清洗: {stats["unit"]:,} 条')
print(f'  型号清洗: {stats["model"]:,} 条')

# ============================================================
# 检查清洗后叶子节点是否有重复
# ============================================================
print('\n检查清洗后叶子节点重复...')
leaves = [r for r in cleaned if r.get('层级') == 13]
leaf_key = lambda r: (r.get('名称',''), r.get('规格',''), r.get('型号',''), r.get('单位',''))
leaf_counter = Counter(leaf_key(r) for r in leaves)
duplicates = {k: v for k, v in leaf_counter.items() if v > 1}
print(f'  叶子节点: {len(leaves):,} 条')
print(f'  唯一组合: {len(leaf_counter):,}')
print(f'  重复组合: {len(duplicates):,}')
print(f'  涉及重复记录: {sum(duplicates.values()):,}')
print(f'  可合并减少: {sum(duplicates.values()) - len(duplicates):,} 条')

if duplicates:
    print('\n  前20个重复项:')
    for (name, spec, model, unit), count in sorted(duplicates.items(), key=lambda x: -x[1])[:20]:
        print(f'    [{count}次] {name} | 规格:{spec or "无"} | 型号:{model or "无"} | 单位:{unit or "无"}')

# ============================================================
# 合并同类项（叶子节点）
# ============================================================
print('\n合并同类项...')
# 按 key 分组叶子节点
leaf_groups = defaultdict(list)
for item in leaves:
    key = leaf_key(item)
    leaf_groups[key].append(item)

# 合并：保留第一条，其他标记为合并
merged_leaves = []
merged_count = 0
for key, items in leaf_groups.items():
    if len(items) > 1:
        # 合并：保留第一条，合并来源信息
        merged = dict(items[0])
        sources = set(item.get('来源', '') for item in items)
        merged['来源'] = '+'.join(sorted(sources))
        if '备注' not in merged or not merged['备注']:
            merged['备注'] = f'合并自{len(items)}条同类项'
        else:
            merged['备注'] = merged['备注'] + f'; 合并自{len(items)}条同类项'
        merged_leaves.append(merged)
        merged_count += len(items) - 1
    else:
        merged_leaves.append(items[0])

print(f'  合并前叶子节点: {len(leaves):,} 条')
print(f'  合并后叶子节点: {len(merged_leaves):,} 条')
print(f'  合并减少: {merged_count:,} 条')

# ============================================================
# 分离分类节点和叶子节点（用原始层级，在层级映射前）
# ============================================================
original_leaf_level = 13
category_nodes_raw = [item for item in cleaned if item.get('层级') != original_leaf_level]
# merged_leaves 已经是合并后的叶子节点（层级还是原始13）

# ============================================================
# 重新分配连续层级
# ============================================================
print('\n重新分配连续层级...')
# 原始层级映射到连续层级
original_levels = sorted(set(item.get('层级') for item in cleaned))
level_map = {old: i+1 for i, old in enumerate(original_levels)}
print(f'  原始层级: {original_levels}')
print(f'  新层级映射: {level_map}')

# 应用层级映射到分类节点和合并后的叶子节点
for item in category_nodes_raw:
    if item.get('层级') in level_map:
        item['层级'] = level_map[item['层级']]
for item in merged_leaves:
    if item.get('层级') in level_map:
        item['层级'] = level_map[item['层级']]

# ============================================================
# 构建最终数据集（分类节点 + 合并后的叶子节点）
# ============================================================
print('\n构建最终数据集...')
final_data = category_nodes_raw + merged_leaves
print(f'  分类节点: {len(category_nodes_raw):,} 条')
print(f'  叶子节点(合并后): {len(merged_leaves):,} 条')
print(f'  最终数据: {len(final_data):,} 条')
print(f'  总减少: {len(data) - len(final_data):,} 条 ({(len(data)-len(final_data))/len(data)*100:.2f}%)')

# ============================================================
# 保存清洗合并后的数据
# ============================================================
print('\n保存结果...')

# JSON 格式
output_json = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_cleaned.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(final_data, f, ensure_ascii=False, indent=2)
print(f'  JSON: {output_json} ({os.path.getsize(output_json):,} bytes)')

# gzip 压缩格式
output_gz = os.path.join(OUTPUT_DIR, 'zhongjian_material_dict_cleaned.json.gz')
with gzip.open(output_gz, 'wt', encoding='utf-8') as f:
    json.dump(final_data, f, ensure_ascii=False)
print(f'  GZIP: {output_gz} ({os.path.getsize(output_gz):,} bytes)')

# 清洗报告
report = {
    '原始数据量': len(data),
    '清洗后数据量': len(cleaned),
    '合并后数据量': len(final_data),
    '总减少量': len(data) - len(final_data),
    '减少比例': f'{(len(data)-len(final_data))/len(data)*100:.2f}%',
    '清洗统计': {
        '名称清洗': stats['name'],
        '规格清洗': stats['spec'],
        '单位清洗': stats['unit'],
        '型号清洗': stats['model'],
    },
    '叶子节点合并': {
        '合并前': len(leaves),
        '合并后': len(merged_leaves),
        '合并减少': merged_count,
        '重复组合数': len(duplicates),
    },
    '层级重映射': level_map,
    '清洗规则': [
        '名称：全角括号→半角括号，去除不可见字符',
        '规格：φ→Φ，数字x数字→数字×数字，去除前后空格',
        '单位：平米→平方米，平方→平方米，kg→千克等同义单位统一',
        '层级：原始不连续层级(4/6/8/9/10/11/12/13/14/16/17/18/19/20/21/23)→连续层级(1-16)',
        '合并：清洗后相同 名称+规格+型号+单位 的叶子节点合并，保留第一条，合并来源信息',
    ],
}
output_report = os.path.join(OUTPUT_DIR, 'cleaning_report.json')
with open(output_report, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'  报告: {output_report}')

print('\n=== 清洗合并完成 ===')
print(f'原始: {len(data):,} 条 → 最终: {len(final_data):,} 条 (减少 {len(data)-len(final_data):,} 条)')
