"""修复未匹配到材料字典的dict:xxx数据，重新计算aggregate_id为正确的code/raw格式"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.boq_item import BoqItem
from app.models.material_dict import MaterialDict
from data.gb_code import compute_match_key
from sqlalchemy import func

db = SessionLocal()

try:
    # 查询所有 aggregate_id 以 dict: 开头但 material_dict_id 仍为 None 的数据
    items = db.query(BoqItem).filter(
        BoqItem.active == True,
        BoqItem.aggregate_id.like('dict:%'),
        BoqItem.material_dict_id == None
    ).all()

    print(f"找到 {len(items)} 条未匹配到材料字典的 dict:xxx 数据")

    # 重新计算 match_key 和 aggregate_id
    fixed = 0
    for item in items:
        # 用 material_dict_id=None 重新计算
        match_key, source = compute_match_key(
            item_code=item.item_code or "",
            item_name=item.item_name or "",
            item_feature=item.item_feature or "",
            unit_std=item.unit_std or "",
            std_name=item.std_name or "",
            std_spec=item.std_spec or "",
            material_dict_id=None,  # 关键：设为None，不使用dict模式
            item_code_version=item.item_code_version or "unknown",
        )
        item.match_key = match_key
        item.match_key_source = source
        # aggregate_id：非dict模式直接用match_key
        item.aggregate_id = match_key
        fixed += 1

    db.commit()
    print(f"修复完成: 重新计算 {fixed} 条数据的 aggregate_id")

    # 验证修复结果
    print("\n修复后 match_key_source 分布:")
    source_rows = db.query(
        BoqItem.match_key_source,
        func.count(BoqItem.id)
    ).filter(BoqItem.active == True).group_by(BoqItem.match_key_source).all()
    for source, cnt in source_rows:
        print(f"  {source}: {cnt}")

    print("\n修复后 aggregate_id 分布（前20个）:")
    agg_rows = db.query(
        BoqItem.aggregate_id,
        func.count(BoqItem.id).label('cnt')
    ).filter(
        BoqItem.active == True,
        BoqItem.unit_rate_num != None
    ).group_by(BoqItem.aggregate_id).order_by(func.count(BoqItem.id).desc()).limit(20).all()
    for agg_id, cnt in agg_rows:
        print(f"  {agg_id}: {cnt}")

    # 有 material_dict_id 的数据
    has_dict = db.query(func.count(BoqItem.id)).filter(
        BoqItem.active == True,
        BoqItem.material_dict_id != None
    ).scalar()
    print(f"\n有 material_dict_id 的数据: {has_dict} 条")

finally:
    db.close()
