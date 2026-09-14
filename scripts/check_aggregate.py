"""查询数据库中boq_item的aggregate_id和material_dict_id分布情况"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.boq_item import BoqItem
from sqlalchemy import func

db = SessionLocal()

try:
    # 总数
    total = db.query(func.count(BoqItem.id)).filter(BoqItem.active == True).scalar()
    print(f"总条目数: {total}")

    # 有material_dict_id的数量
    has_dict = db.query(func.count(BoqItem.id)).filter(
        BoqItem.active == True,
        BoqItem.material_dict_id != None
    ).scalar()
    print(f"有 material_dict_id: {has_dict} ({has_dict/total*100:.1f}%)" if total else "无数据")

    # match_key_source分布
    print("\nmatch_key_source 分布:")
    source_rows = db.query(
        BoqItem.match_key_source,
        func.count(BoqItem.id)
    ).filter(BoqItem.active == True).group_by(BoqItem.match_key_source).all()
    for source, cnt in source_rows:
        print(f"  {source}: {cnt} ({cnt/total*100:.1f}%)" if total else f"  {source}: {cnt}")

    # aggregate_id分布（前20个）
    print("\naggregate_id 分布（前20个）:")
    agg_rows = db.query(
        BoqItem.aggregate_id,
        func.count(BoqItem.id).label('cnt')
    ).filter(
        BoqItem.active == True,
        BoqItem.unit_rate_num != None
    ).group_by(BoqItem.aggregate_id).order_by(func.count(BoqItem.id).desc()).limit(20).all()
    for agg_id, cnt in agg_rows:
        print(f"  {agg_id}: {cnt}")

    # 有单价的条目数
    has_price = db.query(func.count(BoqItem.id)).filter(
        BoqItem.active == True,
        BoqItem.unit_rate_num != None
    ).scalar()
    print(f"\n有单价的条目数: {has_price}")

    # dict模式的aggregate_id示例
    print("\ndict 模式 aggregate_id 示例（前5个）:")
    dict_examples = db.query(BoqItem).filter(
        BoqItem.active == True,
        BoqItem.aggregate_id.like('dict:%')
    ).limit(5).all()
    for item in dict_examples:
        print(f"  id={item.id}, aggregate_id={item.aggregate_id}, material_dict_id={item.material_dict_id}, item_name={item.item_name}")

finally:
    db.close()
