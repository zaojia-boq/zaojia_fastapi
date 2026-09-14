"""
2024清单项目与中建材料字典匹配映射
- 读取2024清单全部项目（5个Sheet）
- 与中建材料字典材料名称层（层级4，约1.3万条）匹配
- 匹配策略：精确匹配 + 模糊匹配（rapidfuzz）
- 输出匹配结果和报告
"""
import gzip, json, os, re
from collections import defaultdict, Counter

# ============================================================
# 1. 读取2024清单
# ============================================================
print('=== 1. 读取2024清单 ===')
excel_path = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GBT50500-2024工程量清单计价.xlsx'

import pandas as pd
xl = pd.ExcelFile(excel_path)
print(f'Sheet列表: {xl.sheet_names}')

# 读取所有专业Sheet（跳过总目录）
all_items = []
for sheet_name in xl.sheet_names:
    if sheet_name == '总目录':
        continue
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    print(f'  {sheet_name}: {len(df)} 行, 列: {list(df.columns)}')
    for _, row in df.iterrows():
        item = {
            '专业': sheet_name,
            '一级分类': str(row.get('一级分类', '')),
            '二级分类': str(row.get('二级分类', '')),
            '三级分类': str(row.get('三级分类', '')),
            '项目编码': str(row.get('项目编码', '')).strip(),
            '项目名称': str(row.get('项目名称', '')).strip(),
            '分类': str(row.get('分类', '')),
            '项目特征': str(row.get('项目特征', '')),
            '计量单位': str(row.get('计量单位', '')),
            '计算规则': str(row.get('计算规则', '')),
        }
        if item['项目编码'] and item['项目编码'] != 'nan':
            all_items.append(item)

print(f'\n清单项目总数: {len(all_items):,}')

# 按专业统计
by_major = Counter(item['专业'] for item in all_items)
print(f'按专业分布: {dict(by_major)}')

# ============================================================
# 2. 读取中建材料字典（材料名称层）
# ============================================================
print('\n=== 2. 读取中建材料字典 ===')
dict_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'
dict_data = json.loads(gzip.open(dict_path, 'rt', encoding='utf-8').read())
print(f'材料字典总数据: {len(dict_data):,} 条')

# 材料名称层（层级4）
material_names = [item for item in dict_data if item['层级'] == 4]
print(f'材料名称层（层级4）: {len(material_names):,} 条')

# 规格叶子层（层级5）
material_specs = [item for item in dict_data if item['层级'] == 5]
print(f'规格叶子层（层级5）: {len(material_specs):,} 条')

# 建立材料名称索引（用于精确匹配）
material_name_index = defaultdict(list)
for item in material_names:
    name = item['名称'].strip()
    material_name_index[name].append(item)

# 材料名称列表（用于模糊匹配）
material_name_list = [item['名称'].strip() for item in material_names]
material_name_unique = list(set(material_name_list))
print(f'唯一材料名称: {len(material_name_unique):,} 个')

# ============================================================
# 3. 匹配函数
# ============================================================
print('\n=== 3. 开始匹配 ===')

# 尝试导入rapidfuzz
try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
    print('使用 rapidfuzz 进行模糊匹配')
except ImportError:
    HAS_RAPIDFUZZ = False
    print('rapidfuzz 未安装，使用内置 difflib')
    from difflib import SequenceMatcher

def exact_match(item_name):
    """精确匹配"""
    return material_name_index.get(item_name, [])

def fuzzy_match(item_name, threshold=70, limit=5):
    """模糊匹配"""
    if HAS_RAPIDFUZZ:
        results = process.extract(item_name, material_name_unique, scorer=fuzz.WRatio, limit=limit)
        return [(name, score) for name, score, _ in results if score >= threshold]
    else:
        # difflib 回退
        scores = []
        for name in material_name_unique:
            ratio = SequenceMatcher(None, item_name, name).ratio() * 100
            if ratio >= threshold:
                scores.append((name, ratio))
        scores.sort(key=lambda x: -x[1])
        return scores[:limit]

def normalize_name(name):
    """名称标准化：去除括号内容、空格、特殊字符"""
    # 去除括号及内容
    name = re.sub(r'[（(].*?[)）]', '', name)
    # 去除空格
    name = name.replace(' ', '')
    # 去除常见后缀
    for suffix in ['制作', '安装', '制作安装', '运输', '采购']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()

# ============================================================
# 4. 执行匹配
# ============================================================
match_results = []
exact_count = 0
fuzzy_count = 0
no_match_count = 0

for i, item in enumerate(all_items):
    if (i + 1) % 500 == 0:
        print(f'  已处理 {i+1}/{len(all_items)}...')

    item_name = item['项目名称']
    normalized = normalize_name(item_name)

    # 精确匹配
    exact = exact_match(item_name)
    exact_normalized = exact_match(normalized) if normalized != item_name else []

    # 模糊匹配
    fuzzy = fuzzy_match(item_name, threshold=75, limit=3)

    if exact or exact_normalized:
        match_type = 'exact'
        matched_materials = exact or exact_normalized
        exact_count += 1
    elif fuzzy:
        match_type = 'fuzzy'
        matched_materials = [{'名称': name, '相似度': score} for name, score in fuzzy]
        fuzzy_count += 1
    else:
        match_type = 'no_match'
        matched_materials = []
        no_match_count += 1

    result = {
        '项目编码': item['项目编码'],
        '项目名称': item['项目名称'],
        '标准化名称': normalized,
        '专业': item['专业'],
        '一级分类': item['一级分类'],
        '二级分类': item['二级分类'],
        '三级分类': item['三级分类'],
        '计量单位': item['计量单位'],
        '匹配类型': match_type,
        '匹配材料': matched_materials if match_type != 'no_match' else [],
        '最佳相似度': matched_materials[0].get('相似度', 100) if matched_materials and isinstance(matched_materials[0], dict) else (100 if matched_materials else 0),
    }
    match_results.append(result)

print(f'\n匹配完成:')
print(f'  精确匹配: {exact_count:,} ({exact_count/len(all_items)*100:.1f}%)')
print(f'  模糊匹配: {fuzzy_count:,} ({fuzzy_count/len(all_items)*100:.1f}%)')
print(f'  未匹配: {no_match_count:,} ({no_match_count/len(all_items)*100:.1f}%)')

# ============================================================
# 5. 按专业统计匹配率
# ============================================================
print('\n=== 5. 按专业匹配率 ===')
by_major_match = defaultdict(lambda: {'exact': 0, 'fuzzy': 0, 'no_match': 0, 'total': 0})
for result in match_results:
    major = result['专业']
    by_major_match[major]['total'] += 1
    by_major_match[major][result['匹配类型']] += 1

for major, stats in sorted(by_major_match.items()):
    rate = (stats['exact'] + stats['fuzzy']) / stats['total'] * 100
    print(f'  {major}: 总计{stats["total"]}, 精确{stats["exact"]}, 模糊{stats["fuzzy"]}, 未匹配{stats["no_match"]}, 匹配率{rate:.1f}%')

# ============================================================
# 6. 输出未匹配项目（供人工审核）
# ============================================================
print('\n=== 6. 未匹配项目示例（前30个）===')
no_match_items = [r for r in match_results if r['匹配类型'] == 'no_match']
for r in no_match_items[:30]:
    print(f'  {r["项目编码"]}: {r["项目名称"]} ({r["专业"]} - {r["二级分类"]})')

# ============================================================
# 7. 保存匹配结果
# ============================================================
print('\n=== 7. 保存匹配结果 ===')
output_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\list_material_mapping'
os.makedirs(output_dir, exist_ok=True)

# 完整匹配结果
output_json = os.path.join(output_dir, 'list_material_match_results.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(match_results, f, ensure_ascii=False, indent=2)
print(f'完整匹配结果: {output_json} ({os.path.getsize(output_json):,} bytes)')

# 匹配映射表（仅精确+高置信模糊）
mapping = []
for r in match_results:
    if r['匹配类型'] == 'exact':
        for mat in r['匹配材料']:
            if isinstance(mat, dict) and '编码' in mat:
                mapping.append({
                    '清单项目编码': r['项目编码'],
                    '清单项目名称': r['项目名称'],
                    '材料编码': mat['编码'],
                    '材料名称': mat['名称'],
                    '匹配类型': '精确匹配',
                    '相似度': 100,
                })
    elif r['匹配类型'] == 'fuzzy' and r['最佳相似度'] >= 85:
        for mat in r['匹配材料']:
            if isinstance(mat, dict) and mat.get('相似度', 0) >= 85:
                # 查找材料编码
                mat_items = material_name_index.get(mat['名称'], [])
                for mi in mat_items:
                    mapping.append({
                        '清单项目编码': r['项目编码'],
                        '清单项目名称': r['项目名称'],
                        '材料编码': mi['编码'],
                        '材料名称': mi['名称'],
                        '匹配类型': '模糊匹配',
                        '相似度': mat['相似度'],
                    })

output_mapping = os.path.join(output_dir, 'list_material_mapping.json')
with open(output_mapping, 'w', encoding='utf-8') as f:
    json.dump(mapping, f, ensure_ascii=False, indent=2)
print(f'匹配映射表（精确+高置信模糊）: {output_mapping} ({len(mapping):,} 条映射)')

# 匹配报告
report = {
    '清单项目总数': len(all_items),
    '材料字典总数': len(dict_data),
    '材料名称数': len(material_names),
    '唯一材料名称数': len(material_name_unique),
    '匹配统计': {
        '精确匹配': exact_count,
        '模糊匹配': fuzzy_count,
        '未匹配': no_match_count,
        '总匹配率': f'{(exact_count + fuzzy_count)/len(all_items)*100:.1f}%',
    },
    '按专业匹配率': {major: {
        '总计': stats['total'],
        '精确': stats['exact'],
        '模糊': stats['fuzzy'],
        '未匹配': stats['no_match'],
        '匹配率': f'{(stats["exact"] + stats["fuzzy"])/stats["total"]*100:.1f}%',
    } for major, stats in by_major_match.items()},
    '匹配映射条数': len(mapping),
}
output_report = os.path.join(output_dir, 'match_report.json')
with open(output_report, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'匹配报告: {output_report}')

# 未匹配项目清单
output_no_match = os.path.join(output_dir, 'unmatched_items.json')
with open(output_no_match, 'w', encoding='utf-8') as f:
    json.dump(no_match_items, f, ensure_ascii=False, indent=2)
print(f'未匹配项目清单: {output_no_match} ({len(no_match_items):,} 条)')

print(f'\n=== 匹配完成 ===')
print(f'输出目录: {output_dir}')
