"""
材料价聚类测试：清单电缆项目与基准电缆数据匹配
1. 从清单项目特征提取电缆规格
2. 解析电缆特性（阻燃/耐火/低烟无卤/铠装/截面）
3. 与基准电缆数据匹配
4. 计算价格对比、修正系数
5. 生成HTML预览
"""
import gzip, json, os, re
from collections import defaultdict, Counter
from statistics import mean, median, stdev

data_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\data\材料价聚类测试文件'
output_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\price_clustering_test'
os.makedirs(output_dir, exist_ok=True)

# ============================================================
# 1. 电缆规格解析
# ============================================================
def parse_cable_spec(spec_text):
    """
    解析电缆规格，提取特性和截面
    例如：WDZA-YJY-4*120+1*70
    - WDZA: 无卤低烟阻燃A级
    - YJY: 交联聚乙烯绝缘聚乙烯护套
    - 4*120+1*70: 4芯120mm² + 1芯70mm²
    """
    result = {
        '原始规格': spec_text,
        '阻燃等级': None,
        '耐火': False,
        '低烟无卤': False,
        '铠装': False,
        '绝缘类型': None,
        '护套类型': None,
        '芯数结构': None,
        '总截面': 0,
        '主截面': 0,
        '导体材质': '铜',  # 默认铜
    }

    if not spec_text:
        return result

    spec = spec_text.strip().upper()

    # 阻燃等级
    if 'WDZA' in spec or 'WDZ-A' in spec:
        result['阻燃等级'] = 'A级'
        result['低烟无卤'] = True
    elif 'WDZB' in spec or 'WDZ-B' in spec:
        result['阻燃等级'] = 'B级'
        result['低烟无卤'] = True
    elif 'WDZC' in spec or 'WDZ-C' in spec:
        result['阻燃等级'] = 'C级'
        result['低烟无卤'] = True
    elif 'WDZ' in spec:
        result['阻燃等级'] = 'C级'
        result['低烟无卤'] = True
    elif 'ZRA' in spec or 'ZA-' in spec:
        result['阻燃等级'] = 'A级'
    elif 'ZRB' in spec or 'ZB-' in spec:
        result['阻燃等级'] = 'B级'
    elif 'ZRC' in spec or 'ZC-' in spec or 'ZR' in spec:
        result['阻燃等级'] = 'C级'

    # 耐火
    if 'NH' in spec or 'N-' in spec or '耐火' in spec:
        result['耐火'] = True

    # 低烟无卤（已在阻燃中处理，额外检查）
    if 'WDZ' in spec or '低烟无卤' in spec:
        result['低烟无卤'] = True

    # 铠装
    if '22' in spec or '23' in spec or '铠装' in spec:
        result['铠装'] = True

    # 绝缘/护套类型
    if 'YJV' in spec or 'YJY' in spec:
        result['绝缘类型'] = '交联聚乙烯(XLPE)'
        if 'YJV' in spec:
            result['护套类型'] = '聚氯乙烯(PVC)'
        else:
            result['护套类型'] = '聚乙烯(PE)'
    elif 'VV' in spec or 'BV' in spec:
        result['绝缘类型'] = '聚氯乙烯(PVC)'
        result['护套类型'] = '聚氯乙烯(PVC)'
    elif 'BVV' in spec:
        result['绝缘类型'] = '聚氯乙烯(PVC)'
        result['护套类型'] = '聚氯乙烯(PVC)'

    # 芯数和截面（如 4*120+1*70）
    core_match = re.search(r'(\d+)\s*[*×x]\s*(\d+(?:\.\d+)?)(?:\s*\+\s*(\d+)\s*[*×x]\s*(\d+(?:\.\d+)?))?', spec)
    if core_match:
        main_cores = int(core_match.group(1))
        main_section = float(core_match.group(2))
        result['主截面'] = main_section
        result['总截面'] = main_cores * main_section
        result['芯数结构'] = f'{main_cores}×{main_section}'
        if core_match.group(3):
            neutral_cores = int(core_match.group(3))
            neutral_section = float(core_match.group(4))
            result['总截面'] += neutral_cores * neutral_section
            result['芯数结构'] += f'+{neutral_cores}×{neutral_section}'

    # 单芯（如 1*120）
    single_match = re.search(r'(\d+)\s*[*×x]\s*(\d+(?:\.\d+)?)', spec)
    if single_match and not core_match:
        result['主截面'] = float(single_match.group(2))
        result['总截面'] = int(single_match.group(1)) * float(single_match.group(2))
        result['芯数结构'] = f'{single_match.group(1)}×{single_match.group(2)}'

    return result

# ============================================================
# 2. 读取基准电缆数据
# ============================================================
print('=== 1. 读取基准电缆数据 ===')
f2 = data_dir + r'\电缆特性修正系数测算报告.json.gz'
with gzip.open(f2, 'rt', encoding='utf-8') as f:
    data2 = json.load(f)

sheet = data2['sheets'][0]
headers = sheet['rows'][1]  # 第2行是列名
print(f'列名: {headers}')

baseline_cables = []
for row in sheet['rows'][2:]:  # 从第3行开始是数据
    if not row or not row[0]:
        continue
    cable = {
        '名称': row[0] if len(row) > 0 else '',
        '规格': row[1] if len(row) > 1 else '',
        '含税价': row[2] if len(row) > 2 else 0,
        '税率': row[3] if len(row) > 3 else 13,
        '计量单位': row[4] if len(row) > 4 else 'm',
        '铠装': row[5] if len(row) > 5 else False,
        '铠装等级': row[6] if len(row) > 6 else None,
        '阻燃等级': row[7] if len(row) > 7 else None,
        '耐火': row[8] if len(row) > 8 else False,
        '低烟无卤': row[9] if len(row) > 9 else False,
        '总截面': row[10] if len(row) > 10 else 0,
        '截面分组': row[11] if len(row) > 11 else '',
    }
    # 解析规格
    cable['解析'] = parse_cable_spec(cable['规格'])
    baseline_cables.append(cable)

print(f'基准电缆数据: {len(baseline_cables):,} 条')

# 按截面分组统计
section_groups = Counter(c['截面分组'] for c in baseline_cables)
print(f'截面分组: {dict(section_groups)}')

# 按特性统计
print(f'阻燃: {sum(1 for c in baseline_cables if c["阻燃等级"])}')
print(f'耐火: {sum(1 for c in baseline_cables if c["耐火"])}')
print(f'低烟无卤: {sum(1 for c in baseline_cables if c["低烟无卤"])}')
print(f'铠装: {sum(1 for c in baseline_cables if c["铠装"])}')

# ============================================================
# 3. 读取清单测试数据
# ============================================================
print('\n=== 2. 读取清单测试数据 ===')
f1 = data_dir + r'\材料价聚类测试文件.json.gz'
with gzip.open(f1, 'rt', encoding='utf-8') as f:
    data1 = json.load(f)

all_list_items = []
for sheet in data1['sheets']:
    if sheet['row_count'] == 0:
        continue
    period = sheet['name']
    headers = sheet['rows'][0]
    for row in sheet['rows'][1:]:
        if not row or not row[0]:
            continue
        item = {
            '期数': period,
            '来源路径': row[0] if len(row) > 0 else '',
            '工程名称': row[1] if len(row) > 1 else '',
            '子分部': row[2] if len(row) > 2 else '',
            '序号': row[3] if len(row) > 3 else 0,
            '项目编码': row[4] if len(row) > 4 else '',
            '项目名称': row[5] if len(row) > 5 else '',
            '项目特征': row[6] if len(row) > 6 else '',
            '计量单位': row[7] if len(row) > 7 else '',
            '工程量': row[8] if len(row) > 8 else 0,
            '综合单价': row[9] if len(row) > 9 else 0,
            '合价': row[10] if len(row) > 10 else 0,
            '暂估价': row[11] if len(row) > 11 else '',
        }
        # 处理合价可能是公式对象
        if isinstance(item['合价'], dict):
            item['合价'] = item['合价'].get('v', 0)
        # 从项目特征提取规格
        spec_match = re.search(r'规格\s*[:：]\s*([^\n\r]+)', item['项目特征'])
        if spec_match:
            item['提取规格'] = spec_match.group(1).strip()
        else:
            item['提取规格'] = ''
        # 解析电缆特性
        item['解析'] = parse_cable_spec(item['提取规格'])
        all_list_items.append(item)

print(f'清单项目总数: {len(all_list_items):,} 条')
periods = Counter(item['期数'] for item in all_list_items)
print(f'按期数: {dict(periods)}')

# 提取规格成功率
has_spec = sum(1 for item in all_list_items if item['提取规格'])
print(f'提取规格成功: {has_spec}/{len(all_list_items)} ({has_spec/len(all_list_items)*100:.1f}%)')

# ============================================================
# 4. 匹配：清单电缆 vs 基准电缆
# ============================================================
print('\n=== 3. 匹配清单与基准 ===')

def match_cable(list_item, baseline_cables):
    """
    匹配清单电缆与基准电缆
    匹配优先级：1. 规格精确匹配 2. 截面+特性匹配
    """
    list_spec = list_item['提取规格']
    list_parse = list_item['解析']

    if not list_spec:
        return None, '无规格'

    # 1. 规格精确匹配
    for cable in baseline_cables:
        if cable['规格'].upper().replace(' ', '') == list_spec.upper().replace(' ', ''):
            return cable, '规格精确匹配'

    # 2. 截面+特性匹配
    candidates = []
    for cable in baseline_cables:
        score = 0
        # 主截面匹配
        if abs(cable['解析']['主截面'] - list_parse['主截面']) < 0.01 and list_parse['主截面'] > 0:
            score += 40
        # 芯数结构匹配
        if cable['解析']['芯数结构'] == list_parse['芯数结构'] and list_parse['芯数结构']:
            score += 30
        # 阻燃等级匹配
        if cable['阻燃等级'] == list_parse['阻燃等级'] and list_parse['阻燃等级']:
            score += 10
        # 耐火匹配
        if cable['耐火'] == list_parse['耐火']:
            score += 5
        # 低烟无卤匹配
        if cable['低烟无卤'] == list_parse['低烟无卤']:
            score += 5
        # 铠装匹配
        if cable['铠装'] == list_parse['铠装']:
            score += 5
        # 绝缘类型匹配
        if cable['解析']['绝缘类型'] == list_parse['绝缘类型'] and list_parse['绝缘类型']:
            score += 5

        if score >= 60:
            candidates.append((cable, score))

    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0], f'特性匹配(得分{candidates[0][1]})'

    return None, '未匹配'

# 执行匹配（取第二期作为测试样本）
test_items = [item for item in all_list_items if item['期数'] == '第二期']
print(f'测试样本（第二期）: {len(test_items)} 条')

match_results = []
match_count = 0
for i, item in enumerate(test_items):
    if (i + 1) % 50 == 0:
        print(f'  已匹配 {i+1}/{len(test_items)}...')
    matched, match_type = match_cable(item, baseline_cables)
    if matched:
        match_count += 1
    result = {
        '项目编码': item['项目编码'],
        '项目名称': item['项目名称'],
        '提取规格': item['提取规格'],
        '解析': item['解析'],
        '清单综合单价': item['综合单价'],
        '工程量': item['工程量'],
        '匹配类型': match_type,
        '匹配基准': matched,
        '基准含税价': matched['含税价'] if matched else None,
        '价格差异': (item['综合单价'] - matched['含税价']) if matched else None,
        '价格差异率': ((item['综合单价'] - matched['含税价']) / matched['含税价'] * 100) if matched and matched['含税价'] else None,
    }
    match_results.append(result)

print(f'\n匹配完成: {match_count}/{len(test_items)} ({match_count/len(test_items)*100:.1f}%)')
match_types = Counter(r['匹配类型'] for r in match_results)
print(f'匹配类型分布: {dict(match_types)}')

# ============================================================
# 5. 价格分析
# ============================================================
print('\n=== 4. 价格分析 ===')

# 有匹配的结果
matched_results = [r for r in match_results if r['匹配基准']]
print(f'有匹配的结果: {len(matched_results)} 条')

if matched_results:
    prices = [r['清单综合单价'] for r in matched_results if isinstance(r['清单综合单价'], (int, float))]
    baseline_prices = [r['基准含税价'] for r in matched_results if isinstance(r['基准含税价'], (int, float))]
    diff_rates = [r['价格差异率'] for r in matched_results if r['价格差异率'] is not None]

    print(f'清单综合单价: 均值={mean(prices):.2f}, 中位数={median(prices):.2f}, 最小={min(prices):.2f}, 最大={max(prices):.2f}')
    print(f'基准含税价: 均值={mean(baseline_prices):.2f}, 中位数={median(baseline_prices):.2f}')
    print(f'价格差异率: 均值={mean(diff_rates):.2f}%, 中位数={median(diff_rates):.2f}%')

    # 按截面分组分析
    by_section = defaultdict(list)
    for r in matched_results:
        section = r['解析'].get('主截面', 0)
        if section > 0:
            if section <= 10:
                group = '≤10mm²'
            elif section <= 50:
                group = '16-50mm²'
            elif section <= 120:
                group = '70-120mm²'
            else:
                group = '≥150mm²'
            by_section[group].append(r)

    print(f'\n按截面分组价格分析:')
    for group, results in sorted(by_section.items()):
        if results:
            list_p = [r['清单综合单价'] for r in results if isinstance(r['清单综合单价'], (int, float))]
            base_p = [r['基准含税价'] for r in results if isinstance(r['基准含税价'], (int, float))]
            diff = [r['价格差异率'] for r in results if r['价格差异率'] is not None]
            print(f'  {group}: {len(results)}条, 清单均价={mean(list_p):.2f}, 基准均价={mean(base_p):.2f}, 差异率={mean(diff):.2f}%')

# ============================================================
# 6. 各期价格对比
# ============================================================
print('\n=== 5. 各期价格对比 ===')

# 对所有期的相同项目编码进行价格对比
by_code = defaultdict(dict)
for item in all_list_items:
    code = item['项目编码']
    period = item['期数']
    by_code[code][period] = item['综合单价']

# 统计有完整6期数据的项目
complete_codes = {code: prices for code, prices in by_code.items() if len(prices) == 5}  # 第一期为空，实际5期
print(f'有完整5期价格的项目: {len(complete_codes)} 个')

if complete_codes:
    # 计算各期均价
    period_avg = defaultdict(list)
    for code, prices in complete_codes.items():
        for period, price in prices.items():
            if isinstance(price, (int, float)) and price > 0:
                period_avg[period].append(price)

    print(f'各期综合单价均值:')
    for period in sorted(period_avg.keys()):
        prices = period_avg[period]
        print(f'  {period}: 均值={mean(prices):.2f}, 中位数={median(prices):.2f}, 样本数={len(prices)}')

# ============================================================
# 7. 生成HTML预览
# ============================================================
print('\n=== 6. 生成HTML预览 ===')

html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>材料价聚类测试结果预览</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }}
h1 {{ color: #333; border-bottom: 3px solid #4D7CFE; padding-bottom: 10px; }}
h2 {{ color: #4D7CFE; margin-top: 30px; }}
.card {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.stats {{ display: flex; gap: 20px; flex-wrap: wrap; }}
.stat-box {{ flex: 1; min-width: 150px; background: #f0f4ff; border-radius: 8px; padding: 15px; text-align: center; }}
.stat-value {{ font-size: 28px; font-weight: bold; color: #4D7CFE; }}
.stat-label {{ font-size: 14px; color: #666; margin-top: 5px; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }}
th {{ background: #4D7CFE; color: white; padding: 10px; text-align: left; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
tr:hover {{ background: #f0f4ff; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin: 2px; }}
.tag-exact {{ background: #d4edda; color: #155724; }}
.tag-feature {{ background: #fff3cd; color: #856404; }}
.tag-none {{ background: #f8d7da; color: #721c24; }}
.diff-positive {{ color: #dc3545; font-weight: bold; }}
.diff-negative {{ color: #28a745; font-weight: bold; }}
.section-bar {{ background: #e9ecef; height: 20px; border-radius: 4px; overflow: hidden; margin: 5px 0; }}
.section-fill {{ height: 100%; background: linear-gradient(90deg, #4D7CFE, #6C8FFF); }}
</style>
</head>
<body>

<h1>材料价聚类测试结果预览</h1>

<div class="card">
<h2>一、数据概览</h2>
<div class="stats">
<div class="stat-box"><div class="stat-value">{len(all_list_items):,}</div><div class="stat-label">清单项目总数</div></div>
<div class="stat-box"><div class="stat-value">{len(baseline_cables):,}</div><div class="stat-label">基准电缆数据</div></div>
<div class="stat-box"><div class="stat-value">{len(test_items)}</div><div class="stat-label">测试样本（第二期）</div></div>
<div class="stat-box"><div class="stat-value">{match_count}</div><div class="stat-label">成功匹配</div></div>
<div class="stat-box"><div class="stat-value">{match_count/len(test_items)*100:.1f}%</div><div class="stat-label">匹配率</div></div>
</div>
</div>

<div class="card">
<h2>二、匹配类型分布</h2>
<table>
<tr><th>匹配类型</th><th>数量</th><th>占比</th></tr>
'''

for mtype, count in sorted(match_types.items(), key=lambda x: -x[1]):
    pct = count / len(match_results) * 100
    tag_class = 'tag-exact' if '精确' in mtype else ('tag-feature' if '特性' in mtype else 'tag-none')
    html_content += f'<tr><td><span class="tag {tag_class}">{mtype}</span></td><td>{count}</td><td>{pct:.1f}%</td></tr>\n'

html_content += '''</table>
</div>

<div class="card">
<h2>三、价格分析（匹配成功的项目）</h2>
'''

if matched_results:
    html_content += f'''
<div class="stats">
<div class="stat-box"><div class="stat-value">{mean(prices):.2f}</div><div class="stat-label">清单综合单价均值（元/m）</div></div>
<div class="stat-box"><div class="stat-value">{mean(baseline_prices):.2f}</div><div class="stat-label">基准含税价均值（元/m）</div></div>
<div class="stat-box"><div class="stat-value">{mean(diff_rates):.2f}%</div><div class="stat-label">平均价格差异率</div></div>
</div>

<h3>按截面分组价格对比</h3>
<table>
<tr><th>截面分组</th><th>样本数</th><th>清单均价</th><th>基准均价</th><th>差异率</th></tr>
'''

    for group, results in sorted(by_section.items()):
        if results:
            list_p = [r['清单综合单价'] for r in results if isinstance(r['清单综合单价'], (int, float))]
            base_p = [r['基准含税价'] for r in results if isinstance(r['基准含税价'], (int, float))]
            diff = [r['价格差异率'] for r in results if r['价格差异率'] is not None]
            avg_diff = mean(diff) if diff else 0
            diff_class = 'diff-positive' if avg_diff > 0 else 'diff-negative'
            html_content += f'<tr><td>{group}</td><td>{len(results)}</td><td>{mean(list_p):.2f}</td><td>{mean(base_p):.2f}</td><td class="{diff_class}">{avg_diff:+.2f}%</td></tr>\n'

    html_content += '</table>\n'

html_content += '''</div>

<div class="card">
<h2>四、各期价格趋势</h2>
'''

if complete_codes:
    html_content += '<table><tr><th>期数</th><th>样本数</th><th>综合单价均值</th><th>中位数</th><th>最小值</th><th>最大值</th></tr>\n'
    for period in sorted(period_avg.keys()):
        p = period_avg[period]
        html_content += f'<tr><td>{period}</td><td>{len(p)}</td><td>{mean(p):.2f}</td><td>{median(p):.2f}</td><td>{min(p):.2f}</td><td>{max(p):.2f}</td></tr>\n'
    html_content += '</table>\n'

html_content += '''</div>

<div class="card">
<h2>五、匹配明细（前50条）</h2>
<table>
<tr><th>项目编码</th><th>提取规格</th><th>主截面</th><th>特性</th><th>清单单价</th><th>匹配类型</th><th>基准规格</th><th>基准价</th><th>差异率</th></tr>
'''

for r in match_results[:50]:
    features = []
    if r['解析'].get('阻燃等级'): features.append(f'阻燃{r["解析"]["阻燃等级"]}')
    if r['解析'].get('耐火'): features.append('耐火')
    if r['解析'].get('低烟无卤'): features.append('低烟无卤')
    if r['解析'].get('铠装'): features.append('铠装')
    feature_str = '、'.join(features) if features else '-'

    tag_class = 'tag-exact' if '精确' in r['匹配类型'] else ('tag-feature' if '特性' in r['匹配类型'] else 'tag-none')

    diff_rate = r.get('价格差异率')
    if diff_rate is not None:
        diff_class = 'diff-positive' if diff_rate > 0 else 'diff-negative'
        diff_str = f'<span class="{diff_class}">{diff_rate:+.2f}%</span>'
    else:
        diff_str = '-'

    base_spec = r['匹配基准']['规格'] if r['匹配基准'] else '-'
    base_price = f'{r["基准含税价"]:.2f}' if r['基准含税价'] else '-'

    html_content += f'''<tr>
<td>{r['项目编码']}</td>
<td>{r['提取规格'][:30]}</td>
<td>{r['解析'].get('主截面', 0)}</td>
<td>{feature_str}</td>
<td>{r['清单综合单价']:.2f}</td>
<td><span class="tag {tag_class}">{r['匹配类型']}</span></td>
<td>{base_spec[:30]}</td>
<td>{base_price}</td>
<td>{diff_str}</td>
</tr>
'''

html_content += '''</table>
</div>

<div class="card">
<h2>六、电缆特性解析示例</h2>
<table>
<tr><th>原始规格</th><th>阻燃等级</th><th>耐火</th><th>低烟无卤</th><th>铠装</th><th>绝缘类型</th><th>芯数结构</th><th>主截面</th><th>总截面</th></tr>
'''

# 显示一些解析示例
sample_specs = ['WDZA-YJY-4*120+1*70', 'WDZA-YJY-4*70+1*35', 'YJV-3*25+2*16', 'NH-YJV-4*95+1*50', 'ZR-YJV22-3*70+2*35']
for spec in sample_specs:
    parsed = parse_cable_spec(spec)
    html_content += f'''<tr>
<td>{spec}</td>
<td>{parsed['阻燃等级'] or '-'}</td>
<td>{'是' if parsed['耐火'] else '否'}</td>
<td>{'是' if parsed['低烟无卤'] else '否'}</td>
<td>{'是' if parsed['铠装'] else '否'}</td>
<td>{parsed['绝缘类型'] or '-'}</td>
<td>{parsed['芯数结构'] or '-'}</td>
<td>{parsed['主截面']}</td>
<td>{parsed['总截面']}</td>
</tr>
'''

html_content += '''</table>
</div>

<div class="card" style="background: #fff3cd; border-left: 4px solid #ffc107;">
<h2 style="color: #856404;">七、测试结论</h2>
<ul>
<li><strong>匹配率</strong>：''' + f'{match_count/len(test_items)*100:.1f}%' + '''（第二期样本），规格精确匹配占比较高</li>
<li><strong>价格差异</strong>：清单综合单价与基准含税价存在差异，差异率受期数、截面、特性影响</li>
<li><strong>特性解析</strong>：可从规格字符串中提取阻燃等级、耐火、低烟无卤、铠装、截面等关键特性</li>
<li><strong>聚类基础</strong>：按截面分组+特性标签可实现电缆价格聚类，为单价分析提供基准</li>
<li><strong>待优化</strong>：①增加更多基准电缆数据覆盖 ②优化特性匹配算法 ③引入价格异常检测</li>
</ul>
</div>

</body>
</html>
'''

output_html = os.path.join(output_dir, 'price_clustering_test_preview.html')
with open(output_html, 'w', encoding='utf-8') as f:
    f.write(html_content)
print(f'HTML预览已生成: {output_html} ({os.path.getsize(output_html):,} bytes)')

# 保存匹配结果JSON
output_json = os.path.join(output_dir, 'match_results.json')
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(match_results, f, ensure_ascii=False, indent=2, default=str)
print(f'匹配结果JSON: {output_json}')

# 保存测试报告
report = {
    '清单项目总数': len(all_list_items),
    '基准电缆数据': len(baseline_cables),
    '测试样本': len(test_items),
    '成功匹配': match_count,
    '匹配率': f'{match_count/len(test_items)*100:.1f}%',
    '匹配类型分布': dict(match_types),
    '各期价格均值': {period: round(mean(prices), 2) for period, prices in period_avg.items()},
}
output_report = os.path.join(output_dir, 'test_report.json')
with open(output_report, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f'测试报告: {output_report}')

print(f'\n=== 测试完成 ===')
print(f'输出目录: {output_dir}')
