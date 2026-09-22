# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

db = SessionLocal()
try:
    count = db.query(ListMaterialMapping).count()
    print(f"当前映射表总数：{count} 条")

    print("\n=== 按匹配类型统计 ===")
    from sqlalchemy import func
    results = db.query(ListMaterialMapping.match_type, func.count(ListMaterialMapping.id)).group_by(ListMaterialMapping.match_type).all()
    for match_type, cnt in results:
        print(f"  {match_type}: {cnt} 条")

finally:
    db.close()
