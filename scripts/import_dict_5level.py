"""
按5级结构导入中建材料字典到 material_dict 表
层级映射：
- 层级1 -> level='l1' (大类, 39个)
- 层级2 -> level='l2' (中类, 197个)
- 层级3 -> level='l3' (小类, 609个)
- 层级4 -> level='l4' (材料名称, 13,790个)
- 层级5 -> level='l5' (规格叶子, 142,098个)
"""
import gzip, json, sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from collections import defaultdict
from app.db import engine, Base, SessionLocal
from app.models import boq_item, import_batch, material_dict, audit_log, match_cache, cost_catalog, favorite, tag
from app.models.material_dict import MaterialDict

# 确保表存在
Base.metadata.create_all(bind=engine)

dict_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz'

print('加载材料字典...')
with gzip.open(dict_path, 'rt', encoding='utf-8') as f:
    data = json.load(f)
print(f'总记录数: {len(data):,}')

# 建立索引
code_index = {item['编码']: item for item in data}

# 按层级分组
by_level = defaultdict(list)
for item in data:
    by_level[item['层级']].append(item)

for level in sorted(by_level.keys()):
    print(f'  层级{level}: {len(by_level[level]):,}')

db = SessionLocal()

# 清空现有数据
existing_count = db.query(MaterialDict).count()
if existing_count > 0:
    print(f'\n清空现有 material_dict 数据: {existing_count} 条')
    db.query(MaterialDict).delete()
    db.commit()

# 逐层导入，建立编码->数据库id映射
code_to_id = {}
batch_size = 1000

for level in [1, 2, 3, 4, 5]:
    level_str = f'l{level}'
    items = by_level[level]
    print(f'\n导入层级{level} ({level_str})，共 {len(items):,} 条...')

    count = 0
    for item in items:
        parent_code = item.get('父编码', '')
        parent_id = code_to_id.get(parent_code) if parent_code else None

        # 构建cat_l1/l2/l3冗余字段（取祖先链）
        ancestors = []
        current = item
        while current and current['层级'] > 1:
            p_code = current.get('父编码', '')
            current = code_index.get(p_code)
            if current:
                ancestors.append(current['名称'])
        ancestors.reverse()  # 从l1到当前父级

        cat_l1 = ancestors[0] if len(ancestors) >= 1 else (item['名称'] if level == 1 else None)
        cat_l2 = ancestors[1] if len(ancestors) >= 2 else (item['名称'] if level == 2 else None)
        cat_l3 = ancestors[2] if len(ancestors) >= 3 else (item['名称'] if level == 3 else None)

        # 构建synonyms
        synonyms = {
            '原始编码': item['编码'],
            '来源': '中建材料字典',
        }
        if level >= 4:
            synonyms['材料名称'] = item['名称']
        if level == 5:
            synonyms['规格'] = item.get('规格', '')
            synonyms['型号'] = item.get('型号', '')
            synonyms['材质'] = item.get('材质', '')
            synonyms['单位'] = item.get('单位', '')

        # 构建spec_whitelist（仅层级4及以下有意义）
        spec_whitelist = None
        if level == 4:
            # 层级4是材料名称，其下有多个规格
            pass
        elif level == 5:
            spec = item.get('规格', '')
            if spec:
                spec_whitelist = {'规格': spec, '单位': item.get('单位', '')}

        # 构建note
        note_parts = [f'中建材料字典层级{level}，原始编码: {item["编码"]}']
        if item.get('备注'):
            note_parts.append(f'备注: {item["备注"]}')
        if item.get('单位') and level == 5:
            note_parts.append(f'单位: {item["单位"]}')
        note = '; '.join(note_parts)

        node = MaterialDict(
            level=level_str,
            parent_id=parent_id,
            name=item['名称'],
            cat_l1=cat_l1,
            cat_l2=cat_l2,
            cat_l3=cat_l3,
            synonyms=synonyms,
            spec_whitelist=spec_whitelist,
            note=note,
        )
        db.add(node)
        db.flush()
        code_to_id[item['编码']] = node.id
        count += 1

        if count % batch_size == 0:
            db.commit()
            print(f'  已导入 {count:,} / {len(items):,}...')

    db.commit()
    print(f'  层级{level}导入完成: {count:,} 条')

# 验证
print('\n=== 导入验证 ===')
total = db.query(MaterialDict).count()
print(f'总记录数: {total:,}')

for level in ['l1', 'l2', 'l3', 'l4', 'l5']:
    count = db.query(MaterialDict).filter(MaterialDict.level == level).count()
    print(f'  {level}: {count:,}')

print('\n抽样验证（l1前3）:')
for node in db.query(MaterialDict).filter(MaterialDict.level == 'l1').limit(3):
    print(f'  [{node.id}] {node.name} (cat_l1={node.cat_l1})')

print('\n抽样验证（l5前3）:')
for node in db.query(MaterialDict).filter(MaterialDict.level == 'l5').limit(3):
    spec = node.synonyms.get('规格', '') if node.synonyms else ''
    unit = node.synonyms.get('单位', '') if node.synonyms else ''
    print(f'  [{node.id}] {node.name} (规格={spec}, 单位={unit})')

# 验证父子关系
print('\n父子关系验证（随机取一个l5节点的祖先链）:')
sample_l5 = db.query(MaterialDict).filter(MaterialDict.level == 'l5').first()
if sample_l5:
    chain = []
    current = sample_l5
    while current:
        chain.append(f'{current.level}:{current.name}')
        current = current.parent if hasattr(current, 'parent') else None
    print(f'  叶子节点: {sample_l5.name}')
    print(f'  祖先链: {" -> ".join(reversed(chain))}')

db.close()
print('\n=== 5级材料字典导入完成 ===')
