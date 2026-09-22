# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping
from data.category_mapping import CATEGORY_TO_5BIG

db = SessionLocal()
try:
    print('清空现有映射...')
    deleted = db.query(ListMaterialMapping).delete()
    db.commit()
    print(f'已删除 {deleted} 条旧映射')

    csv_path = 'deliverables/list_material_mapping/2024清单_编码名称分类映射表.csv'
    df = pd.read_csv(csv_path)
    print(f'\n读取 2024 清单数据：{len(df)} 条')

    new_mappings = []
    category_stats = {}

    for _, row in df.iterrows():
        code9 = str(row.get('清单编码(9位)', ''))
        name = str(row.get('项目名称', ''))
        category = str(row.get('二级分类', ''))

        if not code9 or code9 == 'nan':
            continue

        big5 = CATEGORY_TO_5BIG.get(category)

        if category not in category_stats:
            category_stats[category] = {'total': 0, 'mapped': 0, 'unmapped': 0}
        category_stats[category]['total'] += 1

        if not big5:
            category_stats[category]['unmapped'] += 1
            continue

        mapping = ListMaterialMapping(
            list_item_code=code9,
            list_item_name=name,
            list_version='2024',
            material_code='',
            material_name=name,  # 用项目名称占位，待用户修改
            match_type='category_pending',
            similarity=0.0,
        )
        new_mappings.append(mapping)
        category_stats[category]['mapped'] += 1

    print(f'\n生成新映射：{len(new_mappings)} 条（分类待确认）')
    db.bulk_save_objects(new_mappings)
    db.commit()

    print('\n=== 分类统计 ===')
    for category, stats in sorted(category_stats.items(), key=lambda x: -x[1]['total']):
        print(f'  {category}: {stats["mapped"]}/{stats["total"]} 已映射')

    print(f'\n总计：{sum(s["mapped"] for s in category_stats.values())}/{sum(s["total"] for s in category_stats.values())}')

finally:
    db.close()
