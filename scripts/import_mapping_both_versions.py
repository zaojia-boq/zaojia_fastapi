"""
创建 list_material_mapping 表（带版本字段）并导入优化后的匹配结果
支持 2013 和 2024 两个版本
"""
import json, sys, os
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import engine, Base, SessionLocal
from app.models import boq_item, import_batch, material_dict, audit_log, match_cache, cost_catalog, favorite, tag, list_material_mapping
from app.models.list_material_mapping import ListMaterialMapping

# 创建表
print('创建 list_material_mapping 表（带版本字段）...')
Base.metadata.create_all(bind=engine)
print('表创建完成')

OUTPUT_DIR = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\list_material_mapping'

db = SessionLocal()

# 清空现有数据
existing_count = db.query(ListMaterialMapping).count()
if existing_count > 0:
    print(f'清空现有数据: {existing_count} 条')
    db.query(ListMaterialMapping).delete()
    db.commit()

# 导入两个版本
for version in ['2013', '2024']:
    mapping_path = os.path.join(OUTPUT_DIR, f'list_material_mapping_{version}_v2.json')
    print(f'\n导入 {version} 版匹配结果: {mapping_path}')

    with open(mapping_path, 'r', encoding='utf-8') as f:
        matched = json.load(f)
    print(f'  匹配记录数: {len(matched):,}')

    count = 0
    for item in matched:
        record = ListMaterialMapping(
            list_version=version,
            list_item_code=item['清单项目编码'],
            list_item_name=item['清单项目名称'],
            material_code=item['材料编码'],
            material_name=item['材料名称'],
            match_type=item['匹配类型'],
            similarity=item['相似度'],
        )
        db.add(record)
        count += 1

        if count % 500 == 0:
            db.commit()
            print(f'  已导入 {count:,}/{len(matched):,}...')

    db.commit()
    print(f'  {version} 版导入完成: {count:,} 条')

# 验证
print(f'\n{"="*60}')
print('=== 导入验证 ===')
total = db.query(ListMaterialMapping).count()
print(f'总记录数: {total:,}')

from sqlalchemy import func
version_stats = db.query(
    ListMaterialMapping.list_version,
    func.count(ListMaterialMapping.id)
).group_by(ListMaterialMapping.list_version).all()
print('\n按版本统计:')
for ver, cnt in version_stats:
    print(f'  {ver}: {cnt:,}')

type_stats = db.query(
    ListMaterialMapping.list_version,
    ListMaterialMapping.match_type,
    func.count(ListMaterialMapping.id)
).group_by(ListMaterialMapping.list_version, ListMaterialMapping.match_type).all()
print('\n按版本+匹配类型统计:')
for ver, mtype, cnt in type_stats:
    print(f'  {ver} - {mtype}: {cnt:,}')

# 相似度分布
print('\n相似度分布:')
for ver in ['2013', '2024']:
    high = db.query(ListMaterialMapping).filter(
        ListMaterialMapping.list_version == ver,
        ListMaterialMapping.similarity >= 90
    ).count()
    medium = db.query(ListMaterialMapping).filter(
        ListMaterialMapping.list_version == ver,
        ListMaterialMapping.similarity >= 75,
        ListMaterialMapping.similarity < 90
    ).count()
    low = db.query(ListMaterialMapping).filter(
        ListMaterialMapping.list_version == ver,
        ListMaterialMapping.similarity < 75
    ).count()
    print(f'  {ver}: 高(>=90)={high:,}, 中(75-89)={medium:,}, 低(<75)={low:,}')

# 抽样验证
print('\n抽样验证（2013版前5条）:')
for record in db.query(ListMaterialMapping).filter(ListMaterialMapping.list_version == '2013').limit(5):
    print(f'  [{record.id}] v={record.list_version} {record.list_item_code} {record.list_item_name} -> {record.material_code} {record.material_name} ({record.match_type}, {record.similarity}%)')

print('\n抽样验证（2024版前5条）:')
for record in db.query(ListMaterialMapping).filter(ListMaterialMapping.list_version == '2024').limit(5):
    print(f'  [{record.id}] v={record.list_version} {record.list_item_code} {record.list_item_name} -> {record.material_code} {record.material_name} ({record.match_type}, {record.similarity}%)')

db.close()
print(f'\n{"="*60}')
print('清单-材料匹配结果（双版本优化版）导入完成！')
