"""
优化版清单-材料字典匹配脚本
优化点：
1. 降低模糊匹配阈值到65
2. 增加部分匹配（清单名称包含材料名称，或材料名称包含清单名称）
3. 深度解析项目特征，提取完整材料名称（不只是关键词）
4. 同义词扩展（混凝土=砼、土方=土、石方=石等）
5. 多材料匹配：一个清单项目可匹配多个材料（取TOP3）
"""
import gzip, json, os, sys, re
from collections import defaultdict, Counter

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
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

FUZZY_THRESHOLD = 65  # 降低阈值
PARTIAL_THRESHOLD = 70  # 部分匹配阈值

# 同义词映射
SYNONYMS = {
    '砼': '混凝土',
    '混凝土': '混凝土',
    '土方': '土',
    '石方': '石',
    '土石方': '土石',
    '砖砌体': '砖',
    '砌块': '砌块',
    '水泥砂浆': '砂浆',
    '混合砂浆': '砂浆',
    '石灰砂浆': '砂浆',
    '沥青砂浆': '砂浆',
    '防水砂浆': '砂浆',
    '保温砂浆': '砂浆',
    '聚合物砂浆': '砂浆',
    '钢筋混凝土': '混凝土',
    '预应力混凝土': '混凝土',
    '素混凝土': '混凝土',
    '轻质混凝土': '混凝土',
    '泡沫混凝土': '混凝土',
    '加气混凝土': '混凝土',
    '耐火混凝土': '混凝土',
    '耐酸混凝土': '混凝土',
    '沥青混凝土': '混凝土',
    '水泥稳定土': '稳定土',
    '石灰稳定土': '稳定土',
    '二灰稳定土': '稳定土',
    '级配碎石': '碎石',
    '级配砂砾': '砂砾',
    '水泥稳定碎石': '碎石',
    '沥青碎石': '碎石',
    '沥青玛蹄脂': '沥青',
    '乳化沥青': '沥青',
    '改性沥青': '沥青',
    '石油沥青': '沥青',
    '煤沥青': '沥青',
    '天然沥青': '沥青',
    '建筑石油沥青': '沥青',
    '道路石油沥青': '沥青',
    '普通硅酸盐水泥': '水泥',
    '矿渣硅酸盐水泥': '水泥',
    '火山灰质硅酸盐水泥': '水泥',
    '粉煤灰硅酸盐水泥': '水泥',
    '复合硅酸盐水泥': '水泥',
    '白色硅酸盐水泥': '水泥',
    '快硬硅酸盐水泥': '水泥',
    '早强硅酸盐水泥': '水泥',
    '抗硫酸盐硅酸盐水泥': '水泥',
    '中热硅酸盐水泥': '水泥',
    '低热矿渣硅酸盐水泥': '水泥',
    '膨胀水泥': '水泥',
    '自应力水泥': '水泥',
    '砌筑水泥': '水泥',
    '垫层': '垫层',
    '找平层': '找平层',
    '防水层': '防水层',
    '保温层': '保温层',
    '隔热层': '隔热层',
    '隔声层': '隔声层',
    '隔汽层': '隔汽层',
    '隔离层': '隔离层',
    '结合层': '结合层',
    '面层': '面层',
    '基层': '基层',
    '垫层': '垫层',
}

# ============================================================
# 加载材料字典
# ============================================================
print('加载材料字典...')
with gzip.open(DICT_PATH, 'rt', encoding='utf-8') as f:
    dict_data = json.load(f)

# 取层级4（材料名称）和层级5（规格）的名称
material_names_4 = [item for item in dict_data if item['层级'] == 4]
material_names_5 = [item for item in dict_data if item['层级'] == 5]
print(f'  材料名称(层级4): {len(material_names_4):,}')
print(f'  规格叶子(层级5): {len(material_names_5):,}')

# 建立材料名称索引（层级4为主）
material_name_list = [m['名称'] for m in material_names_4]
material_code_map = {m['名称']: m['编码'] for m in material_names_4}

# 增加层级5的名称作为补充匹配（去重）
material_name_set = set(material_name_list)
for m in material_names_5:
    if m['名称'] not in material_name_set:
        material_name_list.append(m['名称'])
        material_code_map[m['名称']] = m['编码']
        material_name_set.add(m['名称'])
print(f'  扩展后材料名称总数: {len(material_name_list):,}')

# ============================================================
# 项目特征深度解析
# ============================================================
def extract_materials_deep(feature_text, list_name=''):
    """深度解析项目特征，提取材料名称"""
    if not feature_text:
        return []

    materials = []
    text = feature_text

    # 1. 直接匹配材料字典中的名称（在项目特征中出现的完整材料名称）
    for mat_name in material_name_list:
        if len(mat_name) >= 2 and mat_name in text:
            materials.append((mat_name, 100))

    # 2. 同义词替换后匹配
    for syn, standard in SYNONYMS.items():
        if syn in text and standard in material_name_set:
            materials.append((standard, 95))

    # 3. 正则提取常见材料模式
    patterns = [
        r'([\u4e00-\u9fa5]{2,8}(?:混凝土|水泥|砂浆|沥青|涂料|油漆|防水|保温|隔热|隔声|隔汽|隔离|结合|面层|基层|垫层|找平|砌块|砖|瓦|石|砂|土|木|竹|塑料|橡胶|玻璃|陶瓷|陶|瓷|钢|铁|铜|铝|锌|铅|锡|镍|钛|合金|电缆|电线|管|阀|泵|风机|电机|开关|插座|灯|箱|柜|盘|表|计|器|仪|门|窗|锁|铰链|滑轨|龙骨|吊顶|隔墙|地板|地砖|瓷砖|面砖|石材|大理石|花岗岩|石灰石|砂岩|板|条|线|带|绳|索|链|钉|螺栓|螺母|垫圈|垫片|法兰|接头|弯头|三通|四通|异径|补芯|丝扣|卡箍|抱箍|支架|吊架|托架|预埋件|锚栓|钢筋|型钢|角钢|槽钢|工字钢|H型钢|扁钢|圆钢|螺纹钢|钢管|焊管|镀锌管|无缝管|螺旋管|不锈钢管|铜管|铝管|塑料管|PVC管|PE管|PPR管|PB管|PERT管|HDPE管|MDPE管|LDPE管|ABS管|CPVC管|UPVC管|玻璃钢夹砂管|球墨铸铁管|铸铁管))',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            if m in material_name_set:
                materials.append((m, 90))
            elif len(m) >= 2:
                # 模糊匹配
                if HAS_RAPIDFUZZ:
                    result = process.extractOne(m, material_name_list, scorer=fuzz.WRatio)
                    if result and result[1] >= PARTIAL_THRESHOLD:
                        materials.append((result[0], result[1]))

    # 去重，按相似度排序
    seen = set()
    unique_materials = []
    for mat, score in sorted(materials, key=lambda x: -x[1]):
        if mat not in seen:
            seen.add(mat)
            unique_materials.append((mat, score))

    return unique_materials[:5]  # 最多返回5个材料

# ============================================================
# 匹配函数
# ============================================================
def match_exact(list_name):
    """精确匹配"""
    if list_name in material_code_map:
        return material_code_map[list_name], list_name, 'exact_name', 100
    return None

def match_synonym(list_name):
    """同义词匹配"""
    standard = SYNONYMS.get(list_name)
    if standard and standard in material_code_map:
        return material_code_map[standard], standard, 'synonym_match', 95
    return None

def match_partial(list_name):
    """部分匹配：清单名称包含材料名称，或材料名称包含清单名称"""
    best = None
    best_score = 0

    for mat_name in material_name_list:
        if len(mat_name) < 2 or len(list_name) < 2:
            continue
        # 清单名称包含材料名称
        if mat_name in list_name:
            score = 80 + min(len(mat_name) / len(list_name) * 20, 20)
            if score > best_score:
                best_score = score
                best = (material_code_map[mat_name], mat_name, 'partial_match', round(score, 1))
        # 材料名称包含清单名称
        elif list_name in mat_name and len(list_name) >= 2:
            score = 75 + min(len(list_name) / len(mat_name) * 20, 20)
            if score > best_score:
                best_score = score
                best = (material_code_map[mat_name], mat_name, 'partial_match', round(score, 1))

    return best

def match_fuzzy(list_name):
    """模糊匹配"""
    if HAS_RAPIDFUZZ:
        result = process.extractOne(list_name, material_name_list, scorer=fuzz.WRatio)
        if result and result[1] >= FUZZY_THRESHOLD:
            return material_code_map[result[0]], result[0], 'fuzzy_name', round(result[1], 1)
    else:
        best_match = difflib.get_close_matches(list_name, material_name_list, n=1, cutoff=FUZZY_THRESHOLD/100)
        if best_match:
            ratio = difflib.SequenceMatcher(None, list_name, best_match[0]).ratio() * 100
            return material_code_map[best_match[0]], best_match[0], 'fuzzy_name', round(ratio, 1)
    return None

def match_feature(list_name, feature_text):
    """项目特征深度匹配"""
    materials = extract_materials_deep(feature_text, list_name)
    if materials:
        mat_name, score = materials[0]
        return material_code_map[mat_name], mat_name, 'feature_match', round(score, 1)
    return None

def match_list_item(list_code, list_name, feature_text):
    """多级递进匹配，返回最佳匹配"""
    # 1. 精确匹配
    result = match_exact(list_name)
    if result:
        return result

    # 2. 同义词匹配
    result = match_synonym(list_name)
    if result:
        return result

    # 3. 部分匹配
    result = match_partial(list_name)
    if result:
        return result

    # 4. 模糊匹配
    result = match_fuzzy(list_name)
    if result:
        return result

    # 5. 项目特征匹配
    result = match_feature(list_name, feature_text)
    if result:
        return result

    return None

# ============================================================
# 提取清单项目
# ============================================================
def extract_list_items(file_path, version):
    with gzip.open(file_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)

    items = []
    sheets = data.get('sheets', [])

    for sheet in sheets:
        sheet_name = sheet.get('name', '')
        if version == '2024' and sheet_name == '总目录':
            continue

        rows = sheet.get('rows', [])
        if len(rows) <= 1:
            continue

        header = rows[0]
        try:
            code_idx = header.index('项目编码')
            name_idx = header.index('项目名称')
            feature_idx = header.index('项目特征') if '项目特征' in header else -1
            unit_idx = header.index('计量单位') if '计量单位' in header else -1
        except ValueError:
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
    print(f'处理 GB50500-{version} 清单项目（优化版）')

    items = extract_list_items(file_path, version)
    print(f'提取清单项目: {len(items):,} 条')

    print(f'\n开始匹配（模糊阈值={FUZZY_THRESHOLD}，部分匹配阈值={PARTIAL_THRESHOLD}）...')
    matched = []
    unmatched = []
    match_types = Counter()

    for i, item in enumerate(items):
        result = match_list_item(
            item['清单项目编码'],
            item['清单项目名称'],
            item['项目特征'],
        )
        if result:
            mat_code, mat_name, mtype, score = result
            matched.append({
                '清单项目编码': item['清单项目编码'],
                '清单项目名称': item['清单项目名称'],
                '材料编码': mat_code,
                '材料名称': mat_name,
                '匹配类型': mtype,
                '相似度': score,
                '专业分类': item['专业分类'],
            })
            match_types[mtype] += 1
        else:
            unmatched.append(item)

        if (i + 1) % 500 == 0:
            print(f'  已处理 {i+1:,}/{len(items):,}，匹配 {len(matched):,}，未匹配 {len(unmatched):,}')

    # 统计
    total = len(items)
    matched_count = len(matched)
    unmatched_count = len(unmatched)
    match_rate = matched_count / total * 100 if total > 0 else 0

    print(f'\n=== {version}版优化匹配结果 ===')
    print(f'总项目数: {total:,}')
    print(f'匹配成功: {matched_count:,} ({match_rate:.1f}%)')
    print(f'未匹配: {unmatched_count:,} ({100-match_rate:.1f}%)')
    print(f'\n按匹配类型:')
    for mtype, cnt in match_types.most_common():
        print(f'  {mtype}: {cnt:,} ({cnt/total*100:.1f}%)')

    # 按专业分类匹配率
    print(f'\n按专业分类匹配率:')
    by_category = Counter(item['专业分类'] for item in items)
    matched_by_cat = Counter(m['专业分类'] for m in matched)
    for cat, total_cat in by_category.most_common():
        matched_cat = matched_by_cat.get(cat, 0)
        rate = matched_cat / total_cat * 100 if total_cat > 0 else 0
        print(f'  {cat}: {matched_cat:,}/{total_cat:,} ({rate:.1f}%)')

    # 保存结果
    output_mapping = os.path.join(OUTPUT_DIR, f'list_material_mapping_{version}_v2.json')
    with open(output_mapping, 'w', encoding='utf-8') as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)
    print(f'\n匹配结果已保存: {output_mapping} ({len(matched):,} 条)')

    output_unmatched = os.path.join(OUTPUT_DIR, f'unmatched_items_{version}_v2.json')
    with open(output_unmatched, 'w', encoding='utf-8') as f:
        json.dump(unmatched, f, ensure_ascii=False, indent=2)
    print(f'未匹配项目已保存: {output_unmatched} ({len(unmatched):,} 条)')

    # 保存报告
    report = {
        '版本': version,
        '匹配算法': '优化版v2（精确+同义词+部分匹配+模糊+项目特征深度解析）',
        '模糊阈值': FUZZY_THRESHOLD,
        '部分匹配阈值': PARTIAL_THRESHOLD,
        '总项目数': total,
        '匹配成功': matched_count,
        '未匹配': unmatched_count,
        '匹配率': round(match_rate, 1),
        '按匹配类型': dict(match_types),
        '按专业分类': {cat: {'总数': cnt, '匹配': matched_by_cat.get(cat, 0), '匹配率': round(matched_by_cat.get(cat, 0)/cnt*100, 1) if cnt > 0 else 0} for cat, cnt in by_category.items()},
    }
    output_report = os.path.join(OUTPUT_DIR, f'match_report_{version}_v2.json')
    with open(output_report, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'匹配报告已保存: {output_report}')

print(f'\n{"="*60}')
print('全部版本优化匹配完成！')
