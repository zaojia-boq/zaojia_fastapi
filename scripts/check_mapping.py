"""查询list_material_mapping表数据和boq_item的匹配情况"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping
from app.models.boq_item import BoqItem
from sqlalchemy import func

db = SessionLocal()

try:
    # 1. list_material_mapping表数据量
    total_mapping = db.query(func.count(ListMaterialMapping.id)).scalar()
    print(f"list_material_mapping 表总记录数: {total_mapping}")

    # 按版本分布
    print("\n按版本分布:")
    version_rows = db.query(
        ListMaterialMapping.list_version,
        func.count(ListMaterialMapping.id)
    ).group_by(ListMaterialMapping.list_version).all()
    for ver, cnt in version_rows:
        print(f"  {ver}: {cnt} 条")

    # 按匹配类型分布
    print("\n按匹配类型分布:")
    type_rows = db.query(
        ListMaterialMapping.match_type,
        func.count(ListMaterialMapping.id)
    ).group_by(ListMaterialMapping.match_type).all()
    for mtype, cnt in type_rows:
        print(f"  {mtype}: {cnt} 条")

    # 2. boq_item中的item_code有多少能匹配到list_material_mapping
    boq_items = db.query(BoqItem).filter(
        BoqItem.active == True,
        BoqItem.unit_rate_num != None
    ).all()
    print(f"\nboq_item 中有单价的记录数: {len(boq_items)}")

    # 收集所有item_code
    item_codes = set()
    for item in boq_items:
        if item.item_code:
            # 取前9位
            code_9 = item.item_code[:9] if len(item.item_code) >= 9 else item.item_code
            item_codes.add(code_9)
    print(f"唯一9位国标码数量: {len(item_codes)}")

    # 查询这些code有多少能匹配到
    matched_codes = set()
    if item_codes:
        mapping_rows = db.query(ListMaterialMapping.list_item_code).filter(
            ListMaterialMapping.list_item_code.in_(list(item_codes))
        ).all()
        matched_codes = {r.list_item_code for r in mapping_rows}
    print(f"能匹配到 list_material_mapping 的国标码数量: {len(matched_codes)}")
    print(f"匹配率: {len(matched_codes)/len(item_codes)*100:.1f}%" if item_codes else "无数据")

    # 显示前10个匹配示例
    print("\n前10个匹配示例:")
    if matched_codes:
        sample_codes = list(matched_codes)[:10]
        samples = db.query(ListMaterialMapping).filter(
            ListMaterialMapping.list_item_code.in_(sample_codes)
        ).limit(10).all()
        for s in samples:
            print(f"  {s.list_item_code} {s.list_item_name} -> {s.material_code} {s.material_name} (相似度:{s.similarity:.1f})")

    # 显示未匹配的前10个
    print("\n未匹配的前10个国标码:")
    unmatched = item_codes - matched_codes
    for code in list(unmatched)[:10]:
        # 找一个对应的item_name
        item = db.query(BoqItem).filter(
            BoqItem.item_code.like(f"{code}%"),
            BoqItem.active == True
        ).first()
        name = item.item_name if item else "未知"
        print(f"  {code} {name}")

finally:
    db.close()
