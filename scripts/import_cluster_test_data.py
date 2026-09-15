"""导入材料价聚类测试文件（5期电缆数据）到 boq_item 表。"""
import gzip, json, sys, os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, engine
from app.models.boq_item import BoqItem
from app.models.import_batch import ImportBatch

DATA_PATH = r"E:\DEEPSEEK学习\zaojia_fastapi\data\材料价聚类测试文件\材料价聚类测试文件.json.gz"

def parse_feature_spec(feature_text):
    if not feature_text:
        return ""
    for line in str(feature_text).split("\n"):
        line = line.strip()
        if line.startswith("2.规格") or line.startswith("2. 规格"):
            return line.split(":", 1)[-1].strip() if ":" in line else line
    return ""

def main():
    import logging
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

    with gzip.open(DATA_PATH, 'rt', encoding='utf-8') as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        old = db.query(BoqItem).filter(BoqItem.project_name == "电缆电线测试工程").all()
        print(f"清理旧数据: {len(old)}")
        for item in old:
            db.delete(item)
        db.commit()

        batch = ImportBatch(
            name="材料价聚类测试",
            source_file="材料价聚类测试文件.json.gz",
            row_count=0, imported_count=0,
            data_source_type="completed", active=True,
        )
        db.add(batch)
        db.flush()

        now = datetime.now(timezone.utc)
        rows_to_insert = []
        for sheet in data['sheets']:
            rows = sheet.get('rows', [])
            if len(rows) <= 1:
                continue
            price_period = sheet['name']
            for row in rows[1:]:
                if len(row) < 11:
                    continue
                item_code = str(row[4] or "").strip()
                item_name = str(row[5] or "").strip()
                item_feature = str(row[6] or "").strip()
                unit = str(row[7] or "").strip()
                quantity = row[8] if isinstance(row[8], (int, float)) else 0
                unit_rate = row[9] if isinstance(row[9], (int, float)) else 0
                if not item_code or not item_name or unit_rate <= 0:
                    continue
                spec = parse_feature_spec(item_feature)
                rows_to_insert.append({
                    "import_batch_id": batch.id,
                    "project_name": "电缆电线测试工程",
                    "sub_division": str(row[2] or "电缆电线").strip(),
                    "price_period": price_period,
                    "item_code": item_code, "item_code_raw": item_code,
                    "item_code_version": "2013",
                    "item_name": item_name, "item_feature": item_feature,
                    "unit": unit, "unit_std": unit,
                    "quantity": quantity, "quantity_num": quantity,
                    "unit_rate": unit_rate, "unit_rate_num": unit_rate,
                    "total": unit_rate * quantity, "total_num": unit_rate * quantity,
                    "std_name": item_name, "std_spec": spec,
                    "data_source_type": "completed",
                    "active": True, "orphaned": False,
                    "anomaly_flag": "normal",
                    "match_key": f"std:{item_name}|{spec}|{unit}",
                    "match_key_source": "std",
                    "aggregate_id": f"std:{item_name}|{spec}|{unit}",
                    "create_date": now, "write_date": now,
                })

        batch.row_count = len(rows_to_insert)
        batch.imported_count = len(rows_to_insert)

        print(f"批量插入 {len(rows_to_insert)} 条...")
        db.bulk_insert_mappings(BoqItem, rows_to_insert)
        db.commit()
        print("完成!")

        from sqlalchemy import func
        stats = db.query(BoqItem.price_period, func.count(BoqItem.id)).filter(
            BoqItem.project_name == "电缆电线测试工程"
        ).group_by(BoqItem.price_period).all()
        for p, c in stats:
            print(f"  {p}: {c} 条")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
