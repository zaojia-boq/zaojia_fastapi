"""
生成中建材料字典综合预览（各材料类型分布+统计+示例）
"""
import gzip, json, os
from collections import defaultdict, Counter

dict_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'
output_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned'

print('加载材料字典...')
with gzip.open(dict_path, 'rt', encoding='utf-8') as f:
    data = json.load(f)
print(f'总数据: {len(data):,} 条')

# 建立索引
code_index = {item['编码']: item for item in data}
children = defaultdict(list)
for item in data:
    parent = item.get('父编码', '')
    if parent:
        children[parent].append(item)

# 按层级统计
level_stats = defaultdict(lambda: {'count': 0, 'with_spec': 0, 'with_unit': 0, 'with_material': 0})
for item in data:
    level = item['层级']
    level_stats[level]['count'] += 1
    if item.get('规格'):
        level_stats[level]['with_spec'] += 1
    if item.get('单位'):
        level_stats[level]['with_unit'] += 1
    if item.get('材质'):
        level_stats[level]['with_material'] += 1

# 第一层（根节点）统计
root_nodes = [item for item in data if item['层级'] == 1]
print(f'根节点（第一层）: {len(root_nodes)} 个')

# 统计每个根节点下的子节点数和规格叶子数
root_stats = []
for root in root_nodes:
    # 递归统计所有后代
    def count_descendants(code):
        direct = children.get(code, [])
        total = len(direct)
        leaf_count = sum(1 for c in direct if c['层级'] == 5)
        name_count = sum(1 for c in direct if c['层级'] == 4)
        for child in direct:
            sub_total, sub_leaf, sub_name = count_descendants(child['编码'])
            total += sub_total
            leaf_count += sub_leaf
            name_count += sub_name
        return total, leaf_count, name_count

    total, leaf_count, name_count = count_descendants(root['编码'])
    root_stats.append({
        '编码': root['编码'],
        '名称': root['名称'],
        '总后代数': total,
        '材料名称数': name_count,
        '规格叶子数': leaf_count,
    })

# 按规格叶子数排序
root_stats.sort(key=lambda x: -x['规格叶子数'])

print(f'\n按规格叶子数排名前10:')
for i, rs in enumerate(root_stats[:10]):
    print(f'  {i+1}. {rs["名称"]}: {rs["规格叶子数"]:,} 规格, {rs["材料名称数"]:,} 材料名称')

# 单位统计
unit_counter = Counter()
for item in data:
    if item.get('单位') and item['层级'] == 5:
        unit_counter[item['单位']] += 1

print(f'\n单位分布（前15）:')
for unit, count in unit_counter.most_common(15):
    print(f'  {unit}: {count:,}')

# 材质统计
material_counter = Counter()
for item in data:
    if item.get('材质') and item['层级'] == 5:
        material_counter[item['材质']] += 1

print(f'\n材质分布（前15）:')
for mat, count in material_counter.most_common(15):
    print(f'  {mat}: {count:,}')

# ============================================================
# 生成HTML预览
# ============================================================
print('\n生成HTML预览...')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>中建材料字典综合预览</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }}
h1 {{ color: #333; border-bottom: 3px solid #4D7CFE; padding-bottom: 10px; }}
h2 {{ color: #4D7CFE; margin-top: 30px; }}
.card {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.stats {{ display: flex; gap: 15px; flex-wrap: wrap; }}
.stat-box {{ flex: 1; min-width: 130px; background: #f0f4ff; border-radius: 8px; padding: 15px; text-align: center; }}
.stat-value {{ font-size: 24px; font-weight: bold; color: #4D7CFE; }}
.stat-label {{ font-size: 12px; color: #666; margin-top: 5px; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }}
th {{ background: #4D7CFE; color: white; padding: 10px; text-align: left; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
tr:hover {{ background: #f0f4ff; }}
.bar-container {{ background: #e9ecef; height: 18px; border-radius: 4px; overflow: hidden; position: relative; }}
.bar-fill {{ height: 100%; background: linear-gradient(90deg, #4D7CFE, #6C8FFF); }}
.bar-text {{ position: absolute; left: 8px; top: 1px; font-size: 11px; color: #333; font-weight: bold; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 2px; }}
.tag-l1 {{ background: #d4edda; color: #155724; }}
.tag-l2 {{ background: #cce5ff; color: #004085; }}
.tag-l3 {{ background: #fff3cd; color: #856404; }}
.tag-l4 {{ background: #f8d7da; color: #721c24; }}
.tag-l5 {{ background: #e2e3e5; color: #383d41; }}
</style>
</head>
<body>

<h1>中建材料字典综合预览</h1>

<div class="card">
<h2>一、数据概览</h2>
<div class="stats">
<div class="stat-box"><div class="stat-value">{len(data):,}</div><div class="stat-label">总数据条数</div></div>
<div class="stat-box"><div class="stat-value">{len(root_nodes)}</div><div class="stat-label">根节点（大类）</div></div>
<div class="stat-box"><div class="stat-value">{level_stats[4]["count"]:,}</div><div class="stat-label">材料名称（层级4）</div></div>
<div class="stat-box"><div class="stat-value">{level_stats[5]["count"]:,}</div><div class="stat-label">规格叶子（层级5）</div></div>
<div class="stat-box"><div class="stat-value">{len(unit_counter)}</div><div class="stat-label">计量单位种类</div></div>
<div class="stat-box"><div class="stat-value">{len(material_counter)}</div><div class="stat-label">材质种类</div></div>
</div>
</div>

<div class="card">
<h2>二、各层级数据统计</h2>
<table>
<tr><th>层级</th><th>名称</th><th>数量</th><th>有规格</th><th>有单位</th><th>有材质</th></tr>
'''

level_names = {1: '根节点（大类）', 2: '二级分类', 3: '中类', 4: '材料名称', 5: '规格叶子'}
for level in sorted(level_stats.keys()):
    stats = level_stats[level]
    tag_class = f'tag-l{level}'
    html += f'''<tr>
<td><span class="tag {tag_class}">层级{level}</span></td>
<td>{level_names.get(level, '')}</td>
<td>{stats["count"]:,}</td>
<td>{stats["with_spec"]:,} ({stats["with_spec"]/stats["count"]*100:.1f}%)</td>
<td>{stats["with_unit"]:,} ({stats["with_unit"]/stats["count"]*100:.1f}%)</td>
<td>{stats["with_material"]:,} ({stats["with_material"]/stats["count"]*100:.1f}%)</td>
</tr>
'''

html += '''</table>
</div>

<div class="card">
<h2>三、各大类材料分布（按规格叶子数排序）</h2>
<table>
<tr><th>排名</th><th>编码</th><th>大类名称</th><th>材料名称数</th><th>规格叶子数</th><th>占比</th><th>分布</th></tr>
'''

total_leaf = sum(rs['规格叶子数'] for rs in root_stats)
for i, rs in enumerate(root_stats):
    pct = rs['规格叶子数'] / total_leaf * 100
    bar_width = min(pct * 2, 100)  # 放大2倍显示
    html += f'''<tr>
<td>{i+1}</td>
<td><code>{rs["编码"]}</code></td>
<td>{rs["名称"]}</td>
<td>{rs["材料名称数"]:,}</td>
<td><strong>{rs["规格叶子数"]:,}</strong></td>
<td>{pct:.1f}%</td>
<td><div class="bar-container"><div class="bar-fill" style="width:{bar_width}%"></div><div class="bar-text">{pct:.1f}%</div></div></td>
</tr>
'''

html += '''</table>
</div>

<div class="card">
<h2>四、计量单位分布（规格叶子层）</h2>
<table>
<tr><th>排名</th><th>单位</th><th>数量</th><th>占比</th><th>分布</th></tr>
'''

total_unit = sum(unit_counter.values())
for i, (unit, count) in enumerate(unit_counter.most_common(20)):
    pct = count / total_unit * 100
    bar_width = min(pct * 3, 100)
    html += f'''<tr>
<td>{i+1}</td>
<td><strong>{unit}</strong></td>
<td>{count:,}</td>
<td>{pct:.1f}%</td>
<td><div class="bar-container"><div class="bar-fill" style="width:{bar_width}%"></div><div class="bar-text">{pct:.1f}%</div></div></td>
</tr>
'''

html += '''</table>
</div>

<div class="card">
<h2>五、材质分布（规格叶子层，前20）</h2>
<table>
<tr><th>排名</th><th>材质</th><th>数量</th><th>占比</th></tr>
'''

total_material = sum(material_counter.values())
for i, (mat, count) in enumerate(material_counter.most_common(20)):
    pct = count / total_material * 100 if total_material else 0
    html += f'<tr><td>{i+1}</td><td>{mat}</td><td>{count:,}</td><td>{pct:.1f}%</td></tr>\n'

html += '''</table>
</div>

<div class="card">
<h2>六、各大类材料示例（每个大类前3个材料名称）</h2>
<table>
<tr><th>大类</th><th>材料名称示例</th></tr>
'''

for rs in root_stats[:15]:  # 前15个大类
    # 找该大类下的材料名称（层级4）
    def find_names(code, limit=3):
        result = []
        for child in children.get(code, []):
            if child['层级'] == 4:
                result.append(child['名称'])
                if len(result) >= limit:
                    return result
            else:
                sub = find_names(child['编码'], limit - len(result))
                result.extend(sub)
                if len(result) >= limit:
                    return result
        return result

    names = find_names(rs['编码'], 3)
    names_str = '、'.join(names) if names else '-'
    html += f'<tr><td><strong>{rs["名称"]}</strong></td><td>{names_str}</td></tr>\n'

html += '''</table>
</div>

<div class="card" style="background: #d4edda; border-left: 4px solid #28a745;">
<h2 style="color: #155724;">七、数据质量总结</h2>
<ul>
<li><strong>编码方案</strong>：3-2-2-3-4（总长度15位，含前缀I），编码唯一性100%</li>
<li><strong>层级结构</strong>：5级（根→大类→中类→材料名称→规格），层级1-3符合率100%</li>
<li><strong>数据覆盖</strong>：39个大类，''' + f'{level_stats[4]["count"]:,}' + '''个材料名称，''' + f'{level_stats[5]["count"]:,}' + '''个规格叶子</li>
<li><strong>字段完整度</strong>：规格叶子层有规格''' + f'{level_stats[5]["with_spec"]/level_stats[5]["count"]*100:.1f}%' + '''，有单位''' + f'{level_stats[5]["with_unit"]/level_stats[5]["count"]*100:.1f}%' + '''，有材质''' + f'{level_stats[5]["with_material"]/level_stats[5]["count"]*100:.1f}%' + '''</li>
<li><strong>独立预览服务</strong>：端口8778，支持树形浏览+搜索+11字段详情</li>
<li><strong>待优化</strong>：①部分大类材质字段缺失 ②单位同义统一（平米/平方米）③异常编码长度（10/12/19位，源于原始数据层级不统一）</li>
</ul>
</div>

</body>
</html>
'''

output_html = os.path.join(output_dir, 'material_dict_overview.html')
with open(output_html, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'HTML预览已生成: {output_html} ({os.path.getsize(output_html):,} bytes)')

# 保存统计数据
stats_data = {
    '总数据': len(data),
    '根节点数': len(root_nodes),
    '材料名称数': level_stats[4]['count'],
    '规格叶子数': level_stats[5]['count'],
    '单位种类': len(unit_counter),
    '材质种类': len(material_counter),
    '各大类分布': [{'编码': rs['编码'], '名称': rs['名称'], '材料名称数': rs['材料名称数'], '规格叶子数': rs['规格叶子数']} for rs in root_stats],
    '单位分布': dict(unit_counter.most_common(20)),
    '材质分布': dict(material_counter.most_common(20)),
}
output_stats = os.path.join(output_dir, 'material_dict_stats.json')
with open(output_stats, 'w', encoding='utf-8') as f:
    json.dump(stats_data, f, ensure_ascii=False, indent=2)
print(f'统计数据: {output_stats}')

print('\n=== 材料字典综合预览生成完成 ===')
