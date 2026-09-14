"""
创建 list_material_mapping 表并导入清单-材料匹配结果
"""
import json, sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine, Base, SessionLocal
from app.models import boq_item, import_batch, material_dict, audit_log, match_cache, cost_catalog, favorite, tag, list_material_mapping
from app.models.list_material_mapping import ListMaterialMapping

# 创建表
print('创建 list_material_mapping 表...')
Base.metadata.create_all(bind=engine)
print('表创建完成')

# 加载匹配结果
mapping_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\list_material_mapping\list_material_mapping_v2.json'
print(f'\n加载匹配结果: {mapping_path}')
with open(mapping_path, 'r', encoding='utf-8') as f:
    mapping = json.load(f)
print(f'匹配记录数: {len(mapping)}')

db = SessionLocal()

# 清空现有数据
existing_count = db.query(ListMaterialMapping).count()
if existing_count > 0:
    print(f'清空现有数据: {existing_count} 条')
    db.query(ListMaterialMapping).delete()
    db.commit()

# 导入数据
print('\n导入匹配结果...')
count = 0
for item in mapping:
    record = ListMaterialMapping(
        list_item_code=item['清单项目编码'],
        list_item_name=item['清单项目名称'],
        material_code=item['材料编码'],
        material_name=item['材料名称'],
        match_type=item['匹配类型'],
        similarity=item['相似度'],
    )
    db.add(record)
    count += 1

    if count % 200 == 0:
        db.commit()
        print(f'  已导入 {count} / {len(mapping)}...')

db.commit()
print(f'导入完成: {count} 条')

# 验证
print('\n=== 导入验证 ===')
total = db.query(ListMaterialMapping).count()
print(f'总记录数: {total}')

# 按匹配类型统计
from sqlalchemy import func
type_stats = db.query(
    ListMaterialMapping.match_type,
    func.count(ListMaterialMapping.id)
).group_by(ListMaterialMapping.match_type).all()
print('\n按匹配类型统计:')
for match_type, cnt in type_stats:
    print(f'  {match_type}: {cnt}')

# 相似度分布
print('\n相似度分布:')
high = db.query(ListMaterialMapping).filter(ListMaterialMapping.similarity >= 90).count()
medium = db.query(ListMaterialMapping).filter(ListMaterialMapping.similarity >= 75, ListMaterialMapping.similarity < 90).count()
low = db.query(ListMaterialMapping).filter(ListMaterialMapping.similarity < 75).count()
print(f'  高相似度(>=90): {high}')
print(f'  中相似度(75-89): {medium}')
print(f'  低相似度(<75): {low}')

# 抽样验证
print('\n抽样验证（前5条）:')
for record in db.query(ListMaterialMapping).limit(5):
    print(f'  [{record.id}] {record.list_item_code} {record.list_item_name} -> {record.material_code} {record.material_name} ({record.match_type}, {record.similarity}%)')

db.close()
print('\n=== 清单-材料匹配结果导入完成 ===')
