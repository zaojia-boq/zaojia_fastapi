"""
扩展价格聚类到其他材料类型（管材/阀门/灯具等）
由于只有电缆有基准价格数据，其他类型生成分布统计预览
"""
import gzip, json, os, re
from collections import defaultdict, Counter

dict_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'
output_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\price_clustering_test'

print('加载材料字典...')
with gzip.open(dict_path, 'rt', encoding='utf-8') as f:
    data = json.load(f)

# 建立索引
code_index = {item['编码']: item for item in data}
children = defaultdict(list)
for item in data:
    parent = item.get('父编码', '')
    if parent:
        children[parent].append(item)

# 定义目标材料类型（大类名称关键词）
target_types = {
    '电线电缆': ['电线电缆', '电缆', '电线'],
    '管材': ['管道安装设备', '金属管', '塑料管', '钢管', 'PVC管', 'PE管'],
    '阀门': ['阀门'],
    '灯具': ['灯具', '照明', '灯'],
    '钢材': ['钢材及有色金属', '型钢', '钢板', '钢管'],
    '五金': ['五金制品'],
    '电气设备': ['电气安装材料及设备', '配电箱', '开关', '插座'],
    '暖通': ['暖气、通风安装材料', '通风', '空调'],
    '保温': ['隔音保温材料', '保温', '隔热'],
    '防水': ['防水防腐防火材料', '防水', '防腐'],
}

# 递归获取某节点下的所有规格叶子
def get_leaves(code):
    result = []
    for child in children.get(code, []):
        if child['层级'] == 5:
            result.append(child)
        else:
            result.extend(get_leaves(child['编码']))
    return result

# 递归获取某节点下的所有材料名称（层级4）
def get_material_names(code):
    result = []
    for child in children.get(code, []):
        if child['层级'] == 4:
            result.append(child)
        else:
            result.extend(get_material_names(child['编码']))
    return result

# 分析每个目标类型
type_stats = {}
for type_name, keywords in target_types.items():
    print(f'\n分析: {type_name}')

    # 找到匹配的根节点
    matched_roots = []
    for root in [item for item in data if item['层级'] == 1]:
        for kw in keywords:
            if kw in root['名称']:
                matched_roots.append(root)
                break

    if not matched_roots:
        # 尝试在第二层找
        for l2 in [item for item in data if item['层级'] == 2]:
            for kw in keywords:
                if kw in l2['名称']:
                    matched_roots.append(l2)
                    break

    all_leaves = []
    all_names = []
    for root in matched_roots:
        all_leaves.extend(get_leaves(root['编码']))
        all_names.extend(get_material_names(root['编码']))

    # 去重
    unique_leaves = list({leaf['编码']: leaf for leaf in all_leaves}.values())
    unique_names = list({name['编码']: name for name in all_names}.values())

    # 单位统计
    unit_counter = Counter(leaf.get('单位', '') for leaf in unique_leaves if leaf.get('单位'))

    # 材质统计
    material_counter = Counter(leaf.get('材质', '') for leaf in unique_leaves if leaf.get('材质'))

    # 规格示例（前10个）
    spec_examples = [leaf.get('规格', '') for leaf in unique_leaves[:10] if leaf.get('规格')]

    # 材料名称示例（前10个）
    name_examples = [name['名称'] for name in unique_names[:10]]

    type_stats[type_name] = {
        '匹配根节点数': len(matched_roots),
        '匹配根节点名称': [r['名称'] for r in matched_roots[:3]],
        '材料名称数': len(unique_names),
        '规格叶子数': len(unique_leaves),
        '单位分布': dict(unit_counter.most_common(10)),
        '材质分布': dict(material_counter.most_common(10)),
        '规格示例': spec_examples,
        '材料名称示例': name_examples,
    }

    print(f'  材料名称: {len(unique_names):,}, 规格: {len(unique_leaves):,}')
    print(f'  单位TOP3: {unit_counter.most_common(3)}')

# ============================================================
# 生成HTML预览
# ============================================================
print('\n生成HTML预览...')

html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>多材料类型价格聚类扩展预览</title>
<style>
body { font-family: "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }
h1 { color: #333; border-bottom: 3px solid #4D7CFE; padding-bottom: 10px; }
h2 { color: #4D7CFE; margin-top: 30px; }
h3 { color: #555; margin-top: 20px; }
.card { background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.stats { display: flex; gap: 15px; flex-wrap: wrap; }
.stat-box { flex: 1; min-width: 120px; background: #f0f4ff; border-radius: 8px; padding: 12px; text-align: center; }
.stat-value { font-size: 22px; font-weight: bold; color: #4D7CFE; }
.stat-label { font-size: 11px; color: #666; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 12px; }
th { background: #4D7CFE; color: white; padding: 8px; text-align: left; }
td { padding: 6px 8px; border-bottom: 1px solid #eee; }
tr:hover { background: #f0f4ff; }
.bar-container { background: #e9ecef; height: 16px; border-radius: 4px; overflow: hidden; position: relative; }
.bar-fill { height: 100%; background: linear-gradient(90deg, #4D7CFE, #6C8FFF); }
.tag { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 11px; margin: 1px; background: #e9ecef; color: #495057; }
.tag-price { background: #d4edda; color: #155724; }
.tag-noprice { background: #fff3cd; color: #856404; }
</style>
</head>
<body>

<h1>多材料类型价格聚类扩展预览</h1>

<div class="card">
<h2>一、概览</h2>
<div class="stats">
'''

for type_name, stats in type_stats.items():
    has_price = '有基准价' if type_name == '电线电缆' else '待补充基准价'
    tag_class = 'tag-price' if type_name == '电线电缆' else 'tag-noprice'
    html += f'''<div class="stat-box">
<div class="stat-value">{stats["规格叶子数"]:,}</div>
<div class="stat-label">{type_name}<br><span class="tag {tag_class}">{has_price}</span></div>
</div>
'''

html += '''</div>
<p style="margin-top:15px;color:#666;font-size:13px;">
<strong>说明</strong>：当前仅「电线电缆」有基准价格数据（天津地区2,043条），已完成价格聚类测试 V2。
其他材料类型（管材/阀门/灯具/钢材/五金/电气设备/暖通/保温/防水）已完成分布统计，
待补充基准价格数据后可进行价格聚类分析。
</p>
</div>
'''

# 每个类型的详细统计
for type_name, stats in type_stats.items():
    html += f'''
<div class="card">
<h2>{type_name}</h2>
<div class="stats">
<div class="stat-box"><div class="stat-value">{stats["材料名称数"]:,}</div><div class="stat-label">材料名称数</div></div>
<div class="stat-box"><div class="stat-value">{stats["规格叶子数"]:,}</div><div class="stat-label">规格叶子数</div></div>
<div class="stat-box"><div class="stat-value">{len(stats["单位分布"])}</div><div class="stat-label">计量单位种类</div></div>
<div class="stat-box"><div class="stat-value">{len(stats["材质分布"])}</div><div class="stat-label">材质种类</div></div>
</div>

<h3>单位分布（TOP10）</h3>
<table>
<tr><th>单位</th><th>数量</th><th>占比</th><th>分布</th></tr>
'''
    total_units = sum(stats['单位分布'].values())
    for unit, count in list(stats['单位分布'].items())[:10]:
        pct = count / total_units * 100 if total_units else 0
        bar_width = min(pct * 2, 100)
        html += f'<tr><td><strong>{unit}</strong></td><td>{count:,}</td><td>{pct:.1f}%</td><td><div class="bar-container"><div class="bar-fill" style="width:{bar_width}%"></div></div></td></tr>\n'

    html += '''</table>

<h3>材质分布（TOP10）</h3>
<table>
<tr><th>材质</th><th>数量</th></tr>
'''
    for mat, count in list(stats['材质分布'].items())[:10]:
        html += f'<tr><td>{mat}</td><td>{count:,}</td></tr>\n'

    html += '''</table>

<h3>材料名称示例（前10）</h3>
<p>
'''
    for name in stats['材料名称示例'][:10]:
        html += f'<span class="tag">{name}</span> '

    html += '''</p>

<h3>规格示例（前10）</h3>
<p>
'''
    for spec in stats['规格示例'][:10]:
        html += f'<span class="tag">{spec}</span> '

    html += '''</p>
</div>
'''

# 价格聚类扩展路线图
html += '''
<div class="card" style="background: #d4edda; border-left: 4px solid #28a745;">
<h2 style="color: #155724;">价格聚类扩展路线图</h2>
<table>
<tr><th>阶段</th><th>材料类型</th><th>状态</th><th>依赖</th></tr>
<tr><td>第一阶段</td><td>电线电缆</td><td><span class="tag tag-price">已完成 V2</span></td><td>天津地区基准价 2,043 条</td></tr>
<tr><td>第二阶段</td><td>管材（钢管/PVC/PE）</td><td><span class="tag tag-noprice">分布统计完成</span></td><td>待补充管材基准价格数据</td></tr>
<tr><td>第二阶段</td><td>阀门</td><td><span class="tag tag-noprice">分布统计完成</span></td><td>待补充阀门基准价格数据</td></tr>
<tr><td>第三阶段</td><td>灯具/电气设备</td><td><span class="tag tag-noprice">分布统计完成</span></td><td>待补充基准价格数据</td></tr>
<tr><td>第三阶段</td><td>钢材/五金</td><td><span class="tag tag-noprice">分布统计完成</span></td><td>待补充基准价格数据</td></tr>
<tr><td>第四阶段</td><td>暖通/保温/防水</td><td><span class="tag tag-noprice">分布统计完成</span></td><td>待补充基准价格数据</td></tr>
</table>

<h3>基准价格数据来源建议</h3>
<ul>
<li>各地造价信息价（北京/湖南/辽宁/云南等月度信息价）</li>
<li>电商平台市场价（京东/淘宝/1688 工业品）</li>
<li>历史采购成交价（企业内部数据）</li>
<li>广联达/智多星等造价软件材料价库</li>
</ul>
</div>

</body>
</html>
'''

output_html = os.path.join(output_dir, 'multi_material_price_clustering.html')
with open(output_html, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'HTML预览已生成: {output_html} ({os.path.getsize(output_html):,} bytes)')

# 保存统计数据
output_stats = os.path.join(output_dir, 'multi_material_stats.json')
with open(output_stats, 'w', encoding='utf-8') as f:
    json.dump(type_stats, f, ensure_ascii=False, indent=2, default=str)
print(f'统计数据: {output_stats}')

print('\n=== 多材料类型价格聚类扩展完成 ===')
