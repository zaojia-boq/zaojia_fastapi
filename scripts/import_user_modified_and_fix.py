# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

db = SessionLocal()
try:
    # 读取用户手动修改后的文件
    xlsx_path = 'deliverables/list_material_mapping/映射表_手动修改版.xlsx'
    df = pd.read_excel(xlsx_path)
    print(f"读取用户修改版：{len(df)} 条")

    # 清空旧数据
    db.query(ListMaterialMapping).delete()
    db.commit()
    print("已清空旧映射")

    # 导入用户修改版
    new_mappings = []
    for _, row in df.iterrows():
        mapping = ListMaterialMapping(
            list_item_code=str(row.get('list_item_code', '')),
            list_item_name=str(row.get('list_item_name', '')),
            list_version=str(row.get('list_version', '')),
            material_code=str(row.get('material_code', '')),
            material_name=str(row.get('material_name', '')),
            match_type=str(row.get('match_type', 'manual_confirm')),
            similarity=float(row.get('similarity', 100.0)),
        )
        new_mappings.append(mapping)

    db.bulk_save_objects(new_mappings)
    db.commit()
    print(f"已导入用户修改版：{len(new_mappings)} 条")

    # 补充2013钢筋映射
    rebar_codes = ['10515001', '10515002', '10515003', '10515004', '10515005',
                   '10515006', '10515007', '10515008', '10516001', '10516002']

    # 读取2013清单建筑工程获取项目名称
    xlsx_2013 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GB50500-2013清单项目_规范提取版_PDF校正.xlsx'
    df_2013 = pd.read_excel(xlsx_2013, sheet_name='建筑工程')

    rebar_mappings = []
    print(f"\n补充2013钢筋映射：")

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

            if not existing:
                mapping = ListMaterialMapping(
                    list_item_code=code9,
                    list_item_name=name,
                    list_version='2013',
                    material_code='',
                    material_name='钢筋',
                    match_type='category_mapped',
                    similarity=80.0,
                )
                rebar_mappings.append(mapping)
                print(f"  新增：{code9} {name} → 钢筋")

    if rebar_mappings:
        db.bulk_save_objects(rebar_mappings)
        db.commit()
        print(f"\n新增 {len(rebar_mappings)} 条钢筋映射")

    # 统计
    total_count = db.query(ListMaterialMapping).count()
    print(f"\n数据库总映射数：{total_count} 条")

    print("\n=== 按版本统计 ===")
    from sqlalchemy import func
    version_stats = db.query(ListMaterialMapping.list_version, func.count(ListMaterialMapping.id)).group_by(ListMaterialMapping.list_version).all()
    for version, cnt in version_stats:
        print(f"  {version}: {cnt} 条")

    # 钢筋统计
    rebar_count = db.query(ListMaterialMapping).filter(
        ListMaterialMapping.material_name == '钢筋'
    ).count()
    print(f"\n钢筋映射总数：{rebar_count} 条")

finally:
    db.close()
