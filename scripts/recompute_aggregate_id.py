"""重算所有 boq_item 的 aggregate_id（加入规格维度）。"""
import sys
sys.path.insert(0, '.')
from app.db import SessionLocal
from app.models.boq_item import BoqItem, _extract_spec
from sqlalchemy import text

db = SessionLocal()
try:
    items = db.query(BoqItem).filter(BoqItem.material_dict_id.isnot(None)).all()
    updated = 0
    for item in items:
        spec = _extract_spec(item.item_feature or "")
        if item.std_spec and item.std_spec not in spec:
            spec = (spec + "|" if spec else "") + item.std_spec
        if spec:
            new_agg = f"dict:{item.material_dict_id}:{spec}"
        else:
            new_agg = f"dict:{item.material_dict_id}"
        if item.aggregate_id != new_agg:
            item.aggregate_id = new_agg
            updated += 1
    db.commit()
    print(f"重算完成：共 {len(items)} 条，更新 {updated} 条")
    # 展示前 10 条
    for item in items[:10]:
        print(f"  {item.aggregate_id}")
finally:
    db.close()
