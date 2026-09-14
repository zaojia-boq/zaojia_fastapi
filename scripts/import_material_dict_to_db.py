"""
将中建材料字典（5级结构）导入 FastAPI material_dict 表（3级结构）
映射方案：
- l1 = 第一层（大类，39个）
- l2 = 第二层（中类，197个）
- l3 = 第三层及以下（材料名称+规格，合并为规格集合）
"""
import gzip, json, sys
from collections import defaultdict
from sqlalchemy.orm import Session
from app.db import engine, SessionLocal
from app.models.material_dict import MaterialDict

dict_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'

print('加载材料字典...')
with gzip.open(dict_path, 'rt', encoding='utf-8') as f:
    data = json.load(f)

print(f'总记录数: {len(data):,}')

# 建立索引
code_index = {item['编码']: item for item in data}
children = defaultdict(list)
for item in data:
    parent = item.get('父编码', '')
    if parent:
        children[parent].append(item)

# 递归获取某节点下的所有叶子（层级5）
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

# 开始导入
db = SessionLocal()

# 先清空现有数据（如果有）
existing_count = db.query(MaterialDict).count()
if existing_count > 0:
    print(f'清空现有 material_dict 数据: {existing_count} 条')
    db.query(MaterialDict).delete()
    db.commit()

# ============================================================
# 第一层：l1 大类
# ============================================================
print('\n导入第一层（l1 大类）...')
l1_nodes = [item for item in data if item['层级'] == 1]
l1_id_map = {}  # 编码 -> 数据库id

for item in l1_nodes:
    node = MaterialDict(
        level='l1',
        parent_id=None,
        name=item['名称'],
        cat_l1=item['名称'],
        cat_l2=None,
        cat_l3=None,
        synonyms={'原始编码': item['编码'], '来源': '中建材料字典'},
        spec_whitelist=None,
        note=f'中建材料字典第一层，原始编码: {item["编码"]}',
    )
    db.add(node)
    db.flush()
    l1_id_map[item['编码']] = node.id

print(f'  导入 {len(l1_nodes)} 个 l1 节点')

# ============================================================
# 第二层：l2 中类
# ============================================================
print('\n导入第二层（l2 中类）...')
l2_nodes = [item for item in data if item['层级'] == 2]
l2_id_map = {}  # 编码 -> 数据库id

for item in l2_nodes:
    parent_code = item.get('父编码', '')
    parent_id = l1_id_map.get(parent_code)

    node = MaterialDict(
        level='l2',
        parent_id=parent_id,
        name=item['名称'],
        cat_l1=code_index.get(parent_code, {}).get('名称', ''),
        cat_l2=item['名称'],
        cat_l3=None,
        synonyms={'原始编码': item['编码'], '来源': '中建材料字典'},
        spec_whitelist=None,
        note=f'中建材料字典第二层，原始编码: {item["编码"]}',
    )
    db.add(node)
    db.flush()
    l2_id_map[item['编码']] = node.id

print(f'  导入 {len(l2_nodes)} 个 l2 节点')

# ============================================================
# 第三层及以下：l3 规格集合
# 将第三层（中类）作为l3节点，其下的材料名称和规格作为规格集合
# ============================================================
print('\n导入第三层及以下（l3 规格集合）...')
l3_nodes = [item for item in data if item['层级'] == 3]
l3_count = 0
batch_size = 500

for item in l3_nodes:
    parent_code = item.get('父编码', '')
    # 找到最近的l2祖先
    l2_ancestor = None
    current = item
    while current and current['层级'] > 2:
        parent_code = current.get('父编码', '')
        current = code_index.get(parent_code)
    if current and current['层级'] == 2:
        l2_ancestor = current

    parent_id = l2_id_map.get(l2_ancestor['编码']) if l2_ancestor else None

    # 获取该节点下的所有材料名称和规格
    material_names = get_material_names(item['编码'])
    leaves = get_leaves(item['编码'])

    # 构建规格白名单
    spec_list = []
    for leaf in leaves[:100]:  # 最多100个规格
        spec = leaf.get('规格', '')
        if spec and spec not in spec_list:
            spec_list.append(spec)

    # 构建同义词（材料名称列表）
    name_list = [m['名称'] for m in material_names[:50]]  # 最多50个材料名称

    node = MaterialDict(
        level='l3',
        parent_id=parent_id,
        name=item['名称'],
        cat_l1=l2_ancestor.get('父编码', '') and code_index.get(l2_ancestor.get('父编码', ''), {}).get('名称', '') if l2_ancestor else '',
        cat_l2=l2_ancestor['名称'] if l2_ancestor else '',
        cat_l3=item['名称'],
        synonyms={
            '原始编码': item['编码'],
            '来源': '中建材料字典',
            '材料名称': name_list,
            '材料名称数': len(material_names),
            '规格叶子数': len(leaves),
        },
        spec_whitelist={'规格列表': spec_list, '规格总数': len(leaves)} if spec_list else None,
        note=f'中建材料字典第三层，原始编码: {item["编码"]}，包含 {len(material_names)} 个材料名称，{len(leaves)} 个规格',
    )
    db.add(node)
    l3_count += 1

    if l3_count % batch_size == 0:
        db.commit()
        print(f'  已导入 {l3_count} 个 l3 节点...')

db.commit()
print(f'  共导入 {l3_count} 个 l3 节点')

# ============================================================
# 验证
# ============================================================
print('\n=== 导入验证 ===')
total = db.query(MaterialDict).count()
l1_count = db.query(MaterialDict).filter(MaterialDict.level == 'l1').count()
l2_count = db.query(MaterialDict).filter(MaterialDict.level == 'l2').count()
l3_count = db.query(MaterialDict).filter(MaterialDict.level == 'l3').count()

print(f'总记录数: {total:,}')
print(f'  l1 大类: {l1_count}')
print(f'  l2 中类: {l2_count}')
print(f'  l3 规格集合: {l3_count}')

# 抽样验证
print('\n抽样验证（前5个l1）:')
for node in db.query(MaterialDict).filter(MaterialDict.level == 'l1').limit(5):
    print(f'  [{node.id}] {node.name} (cat_l1={node.cat_l1})')

print('\n抽样验证（前5个l3）:')
for node in db.query(MaterialDict).filter(MaterialDict.level == 'l3').limit(5):
    print(f'  [{node.id}] {node.name} (cat_l3={node.cat_l3}, 规格数={node.synonyms.get("规格叶子数", 0) if node.synonyms else 0})')

db.close()
print('\n=== 材料字典导入完成 ===')
