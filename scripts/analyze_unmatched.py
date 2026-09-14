import gzip, json, os, re
from collections import Counter, defaultdict

BASE_DIR = r'E:\DEEPSEEK学习\zaojia_fastapi'
OUTPUT_DIR = os.path.join(BASE_DIR, r'deliverables\list_material_mapping')

# 加载材料字典
DICT_PATH = os.path.join(BASE_DIR, r'deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz')
with gzip.open(DICT_PATH, 'rt', encoding='utf-8') as f:
    dict_data = json.load(f)
material_names = [item['名称'] for item in dict_data if item['层级'] == 4]
material_name_set = set(material_names)
print(f'材料名称数: {len(material_names):,}')

for version in ['2013', '2024']:
    print(f'\n{"="*60}')
    print(f'分析 {version} 版未匹配项目')

    unmatched_path = os.path.join(OUTPUT_DIR, f'unmatched_items_{version}.json')
    with open(unmatched_path, 'r', encoding='utf-8') as f:
        unmatched = json.load(f)
    print(f'未匹配项目数: {len(unmatched):,}')

    # 按专业分类统计
    by_category = Counter(item['专业分类'] for item in unmatched)
    print('\n按专业分类:')
    for cat, cnt in by_category.most_common():
        print(f'  {cat}: {cnt:,}')

    # 分析项目名称特点
    name_lengths = [len(item['清单项目名称']) for item in unmatched]
    print(f'\n项目名称长度: 平均={sum(name_lengths)/len(name_lengths):.1f}, 最短={min(name_lengths)}, 最长={max(name_lengths)}')

    # 检查是否包含材料关键词
    material_keywords = ['钢', '铁', '铜', '铝', '水泥', '混凝土', '砖', '瓦', '石', '砂', '木', '塑料', '橡胶', '玻璃', '陶瓷', '沥青', '漆', '涂料', '防水', '保温', '电缆', '电线', '管', '阀', '泵', '风机', '电机', '开关', '插座', '灯', '箱', '柜', '表', '门', '窗', '龙骨', '吊顶', '地板', '地砖', '瓷砖', '石材', '板', '钢筋', '型钢', '角钢', '槽钢', '工字钢', '钢管', '螺栓']

    contains_material = 0
    for item in unmatched:
        name = item['清单项目名称']
        feature = item.get('项目特征', '')
        text = name + ' ' + feature
        if any(kw in text for kw in material_keywords):
            contains_material += 1
    print(f'\n包含材料关键词的未匹配项目: {contains_material:,} ({contains_material/len(unmatched)*100:.1f}%)')

    # 抽样查看未匹配项目
    print(f'\n抽样未匹配项目（前20条）:')
    for item in unmatched[:20]:
        feature_preview = item.get('项目特征', '')[:50].replace('\n', ' ')
        print(f'  [{item["清单项目编码"]}] {item["清单项目名称"]} | 特征: {feature_preview}')

    # 分析项目特征中的材料关键词
    print(f'\n项目特征中出现的材料关键词TOP20:')
    keyword_counter = Counter()
    for item in unmatched:
        feature = item.get('项目特征', '')
        name = item['清单项目名称']
        text = name + ' ' + feature
        for kw in material_keywords:
            if kw in text:
                keyword_counter[kw] += 1
    for kw, cnt in keyword_counter.most_common(20):
        print(f'  {kw}: {cnt:,}')
