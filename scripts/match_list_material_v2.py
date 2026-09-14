"""
2024清单项目与中建材料字典匹配映射（增强版）
- 同时考虑项目名称和项目特征
- 从项目特征中提取材料名称、规格、材质关键词
- 匹配策略：精确匹配 + 模糊匹配 + 规格匹配
"""
import gzip, json, os, re
from collections import defaultdict, Counter

# ============================================================
# 1. 项目特征解析
# ============================================================
def parse_project_features(features_text):
    """
    从项目特征文本中提取材料名称、规格、材质关键词
    返回：{'materials': [...], 'specs': [...], 'materials_text': '...'}
    """
    if not features_text or features_text == 'nan':
        return {'materials': [], 'specs': [], 'materials_text': ''}

    result = {'materials': [], 'specs': [], 'materials_text': ''}

    # 常见材料关键词（用于从项目特征中识别材料）
    material_keywords = [
        '圆钢', '螺纹钢', '角钢', '扁钢', '工字钢', '槽钢', '钢板', '钢管',
        '不锈钢', '镀锌', '铝合金', '铜', '铝', '铸铁', '铸钢',
        '水泥', '混凝土', '砂浆', '砂', '石子', '碎石', '卵石',
        '砖', '砌块', '瓦', '石灰', '石膏',
        '木材', '木板', '胶合板', '密度板', '刨花板',
        '玻璃', '瓷砖', '陶瓷', '大理石', '花岗石', '石材',
        '电缆', '电线', '导线', '母线', '桥架', '配电箱', '开关', '插座', '灯具',
        '阀门', '法兰', '弯头', '三通', '四通', '管件', '管道',
        '螺栓', '螺母', '螺钉', '铆钉', '焊条', '焊丝',
        '油漆', '涂料', '防腐', '防火', '防水', '保温', '隔热',
        '塑料', '橡胶', 'PVC', 'PE', 'PPR', 'HDPE',
        '沥青', '油毡', '卷材', '密封胶', '胶粘剂',
    ]

    # 规格正则表达式
    spec_patterns = [
        r'Φ\s*\d+(?:\.\d+)?',  # Φ12, Φ5.5
        r'φ\s*\d+(?:\.\d+)?',  # φ12
        r'DN\s*\d+',  # DN100
        r'dn\s*\d+',
        r'\d+\s*\*\s*\d+(?:\s*\*\s*\d+)?',  # 100*100, 100*100*5
        r'\d+\s*×\s*\d+(?:\s*×\s*\d+)?',  # 100×100
        r'Q\d+',  # Q235, Q345
        r'\d+#',  # 20#, 45#
        r'\d+\s*mm',  # 12mm
        r'\d+\s*cm',
        r'\d+\s*m\b',  # 6m
        r'[A-Z]+\d+',  # YJV, BV, SC
    ]

    # 提取材料关键词
    found_materials = []
    for kw in material_keywords:
        if kw in features_text:
            found_materials.append(kw)
    result['materials'] = list(set(found_materials))

    # 提取规格
    found_specs = []
    for pattern in spec_patterns:
        matches = re.findall(pattern, features_text, re.IGNORECASE)
        found_specs.extend(matches)
    result['specs'] = list(set(found_specs))

    # 材料文本（用于组合匹配）
    result['materials_text'] = ' '.join(found_materials + found_specs)

    return result

# ============================================================
# 2. 读取2024清单
# ============================================================
print('=== 1. 读取2024清单 ===')
excel_path = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GBT50500-2024工程量清单计价.xlsx'

import pandas as pd
xl = pd.ExcelFile(excel_path)

all_items = []
for sheet_name in xl.sheet_names:
    if sheet_name == '总目录':
        continue
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    print(f'  {sheet_name}: {len(df)} 行')
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
            # 解析项目特征
            item['特征解析'] = parse_project_features(item['项目特征'])
            all_items.append(item)

print(f'\n清单项目总数: {len(all_items):,}')

# ============================================================
# 3. 读取中建材料字典
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

# 建立索引
material_name_index = defaultdict(list)
for item in material_names:
    name = item['名称'].strip()
    material_name_index[name].append(item)

# 规格索引：材料名称编码 -> 规格列表
spec_by_parent = defaultdict(list)
for item in material_specs:
    parent = item.get('父编码', '')
    if parent:
        spec_by_parent[parent].append(item)

material_name_list = [item['名称'].strip() for item in material_names]
material_name_unique = list(set(material_name_list))
print(f'唯一材料名称: {len(material_name_unique):,} 个')

# ============================================================
# 4. 匹配函数
# ============================================================
print('\n=== 3. 开始匹配 ===')

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
    print('使用 rapidfuzz')
except ImportError:
    HAS_RAPIDFUZZ = False
    from difflib import SequenceMatcher
    print('使用 difflib')

def exact_match(name):
    return material_name_index.get(name, [])

def fuzzy_match(name, threshold=70, limit=5):
    if HAS_RAPIDFUZZ:
        results = process.extract(name, material_name_unique, scorer=fuzz.WRatio, limit=limit)
        return [(name, score) for name, score, _ in results if score >= threshold]
    else:
        scores = []
        for n in material_name_unique:
            ratio = SequenceMatcher(None, name, n).ratio() * 100
            if ratio >= threshold:
                scores.append((n, ratio))
        scores.sort(key=lambda x: -x[1])
        return scores[:limit]

def normalize_name(name):
    name = re.sub(r'[（(].*?[)）]', '', name)
    name = name.replace(' ', '')
    for suffix in ['制作', '安装', '制作安装', '运输', '采购']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()

def match_spec(spec_text, material_parent_code):
    """在指定材料下匹配规格"""
    specs = spec_by_parent.get(material_parent_code, [])
    if not specs or not spec_text:
        return []

    matched = []
    spec_text_clean = spec_text.replace(' ', '').replace('Φ', '').replace('φ', '')
    for spec_item in specs:
        spec_value = spec_item.get('规格', '').replace(' ', '').replace('Φ', '').replace('φ', '')
        if spec_value and (spec_value in spec_text_clean or spec_text_clean in spec_value):
            matched.append(spec_item)
    return matched

# ============================================================
# 5. 执行匹配
# ============================================================
match_results = []
exact_count = 0
fuzzy_count = 0
feature_match_count = 0
no_match_count = 0

for i, item in enumerate(all_items):
    if (i + 1) % 1000 == 0:
        print(f'  已处理 {i+1}/{len(all_items)}...')

    item_name = item['项目名称']
    normalized = normalize_name(item_name)
    features = item['特征解析']

    # 1. 项目名称精确匹配
    exact = exact_match(item_name)
    exact_normalized = exact_match(normalized) if normalized != item_name else []

    # 2. 项目名称模糊匹配
    fuzzy = fuzzy_match(item_name, threshold=75, limit=3)

    # 3. 项目特征材料匹配
    feature_matches = []
    if features['materials']:
        for mat_kw in features['materials']:
            mat_exact = exact_match(mat_kw)
            if mat_exact:
                for m in mat_exact:
                    feature_matches.append({'material': m, 'source': 'feature_exact', 'keyword': mat_kw})
            else:
                mat_fuzzy = fuzzy_match(mat_kw, threshold=80, limit=1)
                for name, score in mat_fuzzy:
                    for m in material_name_index.get(name, []):
                        feature_matches.append({'material': m, 'source': 'feature_fuzzy', 'keyword': mat_kw, 'score': score})

    # 确定匹配类型和结果
    if exact or exact_normalized:
        match_type = 'exact_name'
        matched_materials = exact or exact_normalized
        exact_count += 1
    elif fuzzy and fuzzy[0][1] >= 85:
        match_type = 'fuzzy_name'
        matched_materials = [{'名称': name, '相似度': score} for name, score in fuzzy]
        fuzzy_count += 1
    elif feature_matches:
        match_type = 'feature_match'
        matched_materials = [fm['material'] for fm in feature_matches[:3]]
        feature_match_count += 1
    elif fuzzy:
        match_type = 'fuzzy_low'
        matched_materials = [{'名称': name, '相似度': score} for name, score in fuzzy]
        fuzzy_count += 1
    else:
        match_type = 'no_match'
        matched_materials = []
        no_match_count += 1

    # 规格匹配（如果有匹配的材料且项目特征有规格）
    spec_matches = []
    if matched_materials and features['specs']:
        for mat in matched_materials[:2]:
            if isinstance(mat, dict) and '编码' in mat:
                specs = match_spec(' '.join(features['specs']), mat['编码'])
                spec_matches.extend(specs)

    result = {
        '项目编码': item['项目编码'],
        '项目名称': item['项目名称'],
        '标准化名称': normalized,
        '专业': item['专业'],
        '一级分类': item['一级分类'],
        '二级分类': item['二级分类'],
        '三级分类': item['三级分类'],
        '计量单位': item['计量单位'],
        '项目特征': item['项目特征'][:200] if item['项目特征'] else '',
        '特征解析': features,
        '匹配类型': match_type,
        '匹配材料': matched_materials if match_type != 'no_match' else [],
        '规格匹配': [{'编码': s['编码'], '名称': s['名称'], '规格': s.get('规格', '')} for s in spec_matches[:5]],
        '最佳相似度': matched_materials[0].get('相似度', 100) if matched_materials and isinstance(matched_materials[0], dict) and '相似度' in matched_materials[0] else (100 if matched_materials else 0),
    }
    match_results.append(result)

print(f'\n匹配完成:')
print(f'  名称精确匹配: {exact_count:,} ({exact_count/len(all_items)*100:.1f}%)')
print(f'  名称模糊匹配: {fuzzy_count:,} ({fuzzy_count/len(all_items)*100:.1f}%)')
print(f'  特征材料匹配: {feature_match_count:,} ({feature_match_count/len(all_items)*100:.1f}%)')
print(f'  未匹配: {no_match_count:,} ({no_match_count/len(all_items)*100:.1f}%)')
print(f'  总匹配率: {(exact_count + fuzzy_count + feature_match_count)/len(all_items)*100:.1f}%')

# ============================================================
# 6. 按专业统计
# ============================================================
print('\n=== 4. 按专业匹配率 ===')
by_major = defaultdict(lambda: {'exact_name': 0, 'fuzzy_name': 0, 'feature_match': 0, 'fuzzy_low': 0, 'no_match': 0, 'total': 0})
for r in match_results:
    major = r['专业']
    by_major[major]['total'] += 1
    by_major[major][r['匹配类型']] += 1

for major, stats in sorted(by_major.items()):
    matched = stats['exact_name'] + stats['fuzzy_name'] + stats['feature_match'] + stats['fuzzy_low']
    rate = matched / stats['total'] * 100
    print(f'  {major}: 总计{stats["total"]}, 精确{stats["exact_name"]}, 模糊{stats["fuzzy_name"]+stats["fuzzy_low"]}, 特征{stats["feature_match"]}, 未匹配{stats["no_match"]}, 匹配率{rate:.1f}%')

# ============================================================
# 7. 保存结果
# ============================================================
print('\n=== 5. 保存结果 ===')
output_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\list_material_mapping'
os.makedirs(output_dir, exist_ok=True)

# 完整匹配结果
output_json = os.path.join(output_dir, 'list_material_match_results_v2.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(match_results, f, ensure_ascii=False, indent=2)
print(f'完整匹配结果: {output_json} ({os.path.getsize(output_json):,} bytes)')

# 匹配映射表
mapping = []
for r in match_results:
    if r['匹配类型'] in ['exact_name', 'fuzzy_name', 'feature_match']:
        for mat in r['匹配材料']:
            if isinstance(mat, dict) and '编码' in mat:
                entry = {
                    '清单项目编码': r['项目编码'],
                    '清单项目名称': r['项目名称'],
                    '材料编码': mat['编码'],
                    '材料名称': mat['名称'],
                    '匹配类型': r['匹配类型'],
                    '相似度': r['最佳相似度'],
                }
                # 规格匹配
                if r['规格匹配']:
                    entry['匹配规格'] = [s['规格'] for s in r['规格匹配']]
                mapping.append(entry)

output_mapping = os.path.join(output_dir, 'list_material_mapping_v2.json')
with open(output_mapping, 'w', encoding='utf-8') as f:
    json.dump(mapping, f, ensure_ascii=False, indent=2)
print(f'匹配映射表: {output_mapping} ({len(mapping):,} 条映射)')

# 匹配报告
report = {
    '清单项目总数': len(all_items),
    '材料字典材料名称数': len(material_names),
    '唯一材料名称数': len(material_name_unique),
    '匹配统计': {
        '名称精确匹配': exact_count,
        '名称模糊匹配': fuzzy_count,
        '特征材料匹配': feature_match_count,
        '未匹配': no_match_count,
        '总匹配率': f'{(exact_count + fuzzy_count + feature_match_count)/len(all_items)*100:.1f}%',
    },
    '按专业匹配率': {major: {
        '总计': stats['total'],
        '精确': stats['exact_name'],
        '模糊': stats['fuzzy_name'] + stats['fuzzy_low'],
        '特征': stats['feature_match'],
        '未匹配': stats['no_match'],
        '匹配率': f'{(stats["exact_name"] + stats["fuzzy_name"] + stats["fuzzy_low"] + stats["feature_match"])/stats["total"]*100:.1f}%',
    } for major, stats in by_major.items()},
    '匹配映射条数': len(mapping),
}
output_report = os.path.join(output_dir, 'match_report_v2.json')
with open(output_report, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'匹配报告: {output_report}')

# 未匹配项目
no_match_items = [r for r in match_results if r['匹配类型'] == 'no_match']
output_no_match = os.path.join(output_dir, 'unmatched_items_v2.json')
with open(output_no_match, 'w', encoding='utf-8') as f:
    json.dump(no_match_items, f, ensure_ascii=False, indent=2)
print(f'未匹配项目清单: {output_no_match} ({len(no_match_items):,} 条)')

print(f'\n=== 匹配完成 ===')
print(f'输出目录: {output_dir}')
