"""
通用清单-材料字典匹配脚本
支持 GB50500-2013 和 GBT50500-2024 两个版本
三级递进匹配：名称精确 -> 名称模糊(rapidfuzz>=75) -> 项目特征解析
"""
import gzip, json, os, sys, re
from collections import defaultdict

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print('警告: rapidfuzz 未安装，将使用内置 difflib')
    import difflib

# ============================================================
# 配置
# ============================================================
BASE_DIR = r'E:\DEEPSEEK学习\zaojia_fastapi'
DICT_PATH = os.path.join(BASE_DIR, r'deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz')
OUTPUT_DIR = os.path.join(BASE_DIR, r'deliverables\list_material_mapping')

LIST_FILES = {
    '2013': os.path.join(BASE_DIR, r'data\材料价聚类测试文件\GB50500-2013清单项目_规范提取版_PDF校正.json.gz'),
    '2024': os.path.join(BASE_DIR, r'data\材料价聚类测试文件\GBT50500-2024工程量清单计价.json.gz'),
}

FUZZY_THRESHOLD = 75  # 模糊匹配阈值

# ============================================================
# 加载材料字典
# ============================================================
print('加载材料字典...')
with gzip.open(DICT_PATH, 'rt', encoding='utf-8') as f:
    dict_data = json.load(f)
print(f'  材料字典总记录: {len(dict_data):,}')

# 只取层级4（材料名称）作为匹配目标
material_names = [item for item in dict_data if item['层级'] == 4]
print(f'  材料名称(层级4): {len(material_names):,}')

# 建立材料名称索引
material_name_list = [m['名称'] for m in material_names]
material_code_map = {m['名称']: m['编码'] for m in material_names}

# ============================================================
# 项目特征解析：提取材料关键词
# ============================================================
def extract_materials_from_feature(feature_text):
    """从项目特征中提取材料关键词"""
    if not feature_text:
        return []

    # 常见材料关键词模式
    material_patterns = [
        r'([\u4e00-\u9fa5]{2,6}(?:钢|铁|铜|铝|锌|铅|锡|镍|钛|合金|混凝土|水泥|砂浆|砖|瓦|石|砂|土|木|竹|塑料|橡胶|玻璃|陶瓷|陶|瓷|沥青|油|漆|涂料|防水|保温|隔热|隔音|防火|防腐|阻燃|耐火|电缆|电线|管|阀|泵|风机|电机|开关|插座|灯|箱|柜|盘|表|计|器|仪|门|窗|锁|铰链|滑轨|龙骨|吊顶|隔墙|地板|地砖|瓷砖|面砖|石材|大理石|花岗岩|石灰石|砂岩|板|条|线|带|绳|索|链|钉|螺栓|螺母|垫圈|垫片|法兰|接头|弯头|三通|四通|异径|补芯|丝扣|卡箍|抱箍|支架|吊架|托架|预埋件|锚栓|钢筋|型钢|角钢|槽钢|工字钢|H型钢|扁钢|圆钢|螺纹钢|钢管|焊管|镀锌管|无缝管|螺旋管|不锈钢管|铜管|铝管|塑料管|PVC管|PE管|PPR管|PB管|PERT管|HDPE管|MDPE管|LDPE管|ABS管|CPVC管|UPVC管|玻璃钢夹砂管|球墨铸铁管|铸铁管|钢管|镀锌钢管|焊接钢管|无缝钢管|螺旋缝钢管|直缝钢管|不锈钢管|铜管|铝塑复合管|钢塑复合管|塑料合金管|玻璃钢管|陶瓷管|水泥管|混凝土管|钢筋混凝土管|预应力混凝土管|自应力混凝土管|石棉水泥管|陶土管|缸瓦管))',
    ]

    materials = []
    for pattern in material_patterns:
        matches = re.findall(pattern, feature_text)
        materials.extend(matches)

    # 去重并过滤太短的
    materials = list(set(m for m in materials if len(m) >= 2))
    return materials

# ============================================================
# 匹配函数
# ============================================================
def match_exact(list_name):
    """精确匹配"""
    if list_name in material_code_map:
        return {
            '材料编码': material_code_map[list_name],
            '材料名称': list_name,
            '匹配类型': 'exact_name',
            '相似度': 100,
        }
    return None

def match_fuzzy(list_name):
    """模糊匹配"""
    if HAS_RAPIDFUZZ:
        result = process.extractOne(list_name, material_name_list, scorer=fuzz.WRatio)
        if result and result[1] >= FUZZY_THRESHOLD:
            return {
                '材料编码': material_code_map[result[0]],
                '材料名称': result[0],
                '匹配类型': 'fuzzy_name',
                '相似度': round(result[1], 1),
            }
    else:
        # 使用difflib
        best_match = difflib.get_close_matches(list_name, material_name_list, n=1, cutoff=FUZZY_THRESHOLD/100)
        if best_match:
            ratio = difflib.SequenceMatcher(None, list_name, best_match[0]).ratio() * 100
            return {
                '材料编码': material_code_map[best_match[0]],
                '材料名称': best_match[0],
                '匹配类型': 'fuzzy_name',
                '相似度': round(ratio, 1),
            }
    return None

def match_feature(list_name, feature_text):
    """项目特征匹配"""
    materials = extract_materials_from_feature(feature_text)
    if not materials:
        return None

    # 对提取的材料关键词进行精确或模糊匹配
    best_result = None
    best_score = 0

    for mat in materials:
        # 精确匹配
        if mat in material_code_map:
            score = 100
            if score > best_score:
                best_score = score
                best_result = {
                    '材料编码': material_code_map[mat],
                    '材料名称': mat,
                    '匹配类型': 'feature_match',
                    '相似度': score,
                }
            continue

        # 模糊匹配
        if HAS_RAPIDFUZZ:
            result = process.extractOne(mat, material_name_list, scorer=fuzz.WRatio)
            if result and result[1] >= FUZZY_THRESHOLD and result[1] > best_score:
                best_score = result[1]
                best_result = {
                    '材料编码': material_code_map[result[0]],
                    '材料名称': result[0],
                    '匹配类型': 'feature_match',
                    '相似度': round(result[1], 1),
                }

    return best_result

def match_list_item(list_code, list_name, feature_text):
    """三级递进匹配"""
    # 1. 精确匹配
    result = match_exact(list_name)
    if result:
        result['清单项目编码'] = list_code
        result['清单项目名称'] = list_name
        return result

    # 2. 模糊匹配
    result = match_fuzzy(list_name)
    if result:
        result['清单项目编码'] = list_code
        result['清单项目名称'] = list_name
        return result

    # 3. 项目特征匹配
    result = match_feature(list_name, feature_text)
    if result:
        result['清单项目编码'] = list_code
        result['清单项目名称'] = list_name
        return result

    return None

# ============================================================
# 提取清单项目
# ============================================================
def extract_list_items(file_path, version):
    """从JSON文件中提取清单项目"""
    with gzip.open(file_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)

    items = []
    sheets = data.get('sheets', [])

    for sheet in sheets:
        sheet_name = sheet.get('name', '')
        # 2024版跳过总目录
        if version == '2024' and sheet_name == '总目录':
            continue

        rows = sheet.get('rows', [])
        if len(rows) <= 1:
            continue

        # 确定列索引
        header = rows[0]
        try:
            code_idx = header.index('项目编码')
            name_idx = header.index('项目名称')
            feature_idx = header.index('项目特征') if '项目特征' in header else -1
            unit_idx = header.index('计量单位') if '计量单位' in header else -1
        except ValueError:
            print(f'  警告: sheet "{sheet_name}" 表头不匹配，跳过')
            continue

        for row in rows[1:]:
            if not row or len(row) <= max(code_idx, name_idx):
                continue
            code = row[code_idx] if code_idx < len(row) else ''
            name = row[name_idx] if name_idx < len(row) else ''
            if not code or not name:
                continue

            feature = row[feature_idx] if feature_idx >= 0 and feature_idx < len(row) else ''
            unit = row[unit_idx] if unit_idx >= 0 and unit_idx < len(row) else ''

            items.append({
                '清单项目编码': str(code).strip(),
                '清单项目名称': str(name).strip(),
                '项目特征': str(feature).strip() if feature else '',
                '计量单位': str(unit).strip() if unit else '',
                '专业分类': sheet_name,
            })

    return items

# ============================================================
# 主流程
# ============================================================
os.makedirs(OUTPUT_DIR, exist_ok=True)

for version, file_path in LIST_FILES.items():
    print(f'\n{"="*60}')
    print(f'处理 GB50500-{version} 清单项目')
    print(f'文件: {file_path}')

    # 提取清单项目
    items = extract_list_items(file_path, version)
    print(f'提取清单项目: {len(items):,} 条')

    # 按专业分类统计
    by_category = defaultdict(int)
    for item in items:
        by_category[item['专业分类']] += 1
    print('按专业分类:')
    for cat, cnt in by_category.items():
        print(f'  {cat}: {cnt:,}')

    # 匹配
    print(f'\n开始匹配（阈值={FUZZY_THRESHOLD}）...')
    matched = []
    unmatched = []
    match_types = defaultdict(int)

    for i, item in enumerate(items):
        result = match_list_item(
            item['清单项目编码'],
            item['清单项目名称'],
            item['项目特征'],
        )
        if result:
            matched.append(result)
            match_types[result['匹配类型']] += 1
        else:
            unmatched.append(item)

        if (i + 1) % 500 == 0:
            print(f'  已处理 {i+1:,}/{len(items):,}，匹配 {len(matched):,}，未匹配 {len(unmatched):,}')

    # 统计
    total = len(items)
    matched_count = len(matched)
    unmatched_count = len(unmatched)
    match_rate = matched_count / total * 100 if total > 0 else 0

    print(f'\n=== {version}版匹配结果 ===')
    print(f'总项目数: {total:,}')
    print(f'匹配成功: {matched_count:,} ({match_rate:.1f}%)')
    print(f'未匹配: {unmatched_count:,} ({100-match_rate:.1f}%)')
    print(f'\n按匹配类型:')
    for mtype, cnt in sorted(match_types.items(), key=lambda x: -x[1]):
        print(f'  {mtype}: {cnt:,} ({cnt/total*100:.1f}%)')

    # 按专业分类匹配率
    print(f'\n按专业分类匹配率:')
    matched_by_cat = defaultdict(int)
    for m in matched:
        # 找到对应的专业分类
        for item in items:
            if item['清单项目编码'] == m['清单项目编码']:
                matched_by_cat[item['专业分类']] += 1
                break
    for cat, total_cat in by_category.items():
        matched_cat = matched_by_cat.get(cat, 0)
        rate = matched_cat / total_cat * 100 if total_cat > 0 else 0
        print(f'  {cat}: {matched_cat:,}/{total_cat:,} ({rate:.1f}%)')

    # 保存结果
    output_mapping = os.path.join(OUTPUT_DIR, f'list_material_mapping_{version}.json')
    with open(output_mapping, 'w', encoding='utf-8') as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)
    print(f'\n匹配结果已保存: {output_mapping} ({len(matched):,} 条)')

    output_unmatched = os.path.join(OUTPUT_DIR, f'unmatched_items_{version}.json')
    with open(output_unmatched, 'w', encoding='utf-8') as f:
        json.dump(unmatched, f, ensure_ascii=False, indent=2)
    print(f'未匹配项目已保存: {output_unmatched} ({len(unmatched):,} 条)')

    # 保存报告
    report = {
        '版本': version,
        '总项目数': total,
        '匹配成功': matched_count,
        '未匹配': unmatched_count,
        '匹配率': round(match_rate, 1),
        '按匹配类型': dict(match_types),
        '按专业分类': {cat: {'总数': cnt, '匹配': matched_by_cat.get(cat, 0), '匹配率': round(matched_by_cat.get(cat, 0)/cnt*100, 1) if cnt > 0 else 0} for cat, cnt in by_category.items()},
    }
    output_report = os.path.join(OUTPUT_DIR, f'match_report_{version}.json')
    with open(output_report, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'匹配报告已保存: {output_report}')

print(f'\n{"="*60}')
print('全部版本匹配完成！')
