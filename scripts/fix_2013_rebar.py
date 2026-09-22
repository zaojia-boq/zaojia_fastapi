# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

db = SessionLocal()
try:
    # 读取2013清单建筑工程
    xlsx_2013 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GB50500-2013清单项目_规范提取版_PDF校正.xlsx'
    df_2013 = pd.read_excel(xlsx_2013, sheet_name='建筑工程')

    # 钢筋相关项目编码（前6位 10515 / 10516）
    rebar_codes = ['10515001', '10515002', '10515003', '10515004', '10515005',
                   '10515006', '10515007', '10515008', '10516001', '10516002']

    print(f"补充2013清单钢筋映射：")
    new_mappings = []

    for _, row in df_2013.iterrows():
        code = str(row.get('项目编码', ''))
        if not code:
            continue

        code8 = code.ljust(8, '0')
        if code8 in rebar_codes:
            code9 = code8.ljust(9, '0')
            name = str(row.get('项目名称', ''))

            # 检查是否已存在
            existing = db.query(ListMaterialMapping).filter(
                ListMaterialMapping.list_version == '2013',
                ListMaterialMapping.list_item_code == code9
            ).first()

            if existing:
                # 更新为钢筋
                existing.material_name = '钢筋'
                existing.match_type = 'category_mapped'
                existing.similarity = 80.0
                print(f"  更新：{code9} {name} → 钢筋")
            else:
                # 新增
                mapping = ListMaterialMapping(
                    list_item_code=code9,
                    list_item_name=name,
                    list_version='2013',
                    material_code='',
                    material_name='钢筋',
                    match_type='category_mapped',
                    similarity=80.0,
                )
                new_mappings.append(mapping)
                print(f"  新增：{code9} {name} → 钢筋")

    if new_mappings:
        db.bulk_save_objects(new_mappings)
        print(f"\n新增 {len(new_mappings)} 条钢筋映射")

    db.commit()

    # 统计
    print(f"\n=== 2013钢筋映射统计 ===")
    rebar_count = db.query(ListMaterialMapping).filter(
        ListMaterialMapping.list_version == '2013',
        ListMaterialMapping.material_name == '钢筋'
    ).count()
    print(f"2013钢筋映射：{rebar_count} 条")

    total_count = db.query(ListMaterialMapping).count()
    print(f"数据库总映射数：{total_count} 条")

finally:
    db.close()
