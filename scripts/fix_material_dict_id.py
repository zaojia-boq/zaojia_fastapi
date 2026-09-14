"""修复boq_item中material_dict_id为None但aggregate_id以dict:开头的数据"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.boq_item import BoqItem
from app.models.material_dict import MaterialDict
from sqlalchemy import func

db = SessionLocal()

try:
    # 查询所有 aggregate_id 以 dict: 开头但 material_dict_id 为 None 的数据
    items = db.query(BoqItem).filter(
        BoqItem.active == True,
        BoqItem.aggregate_id.like('dict:%'),
        BoqItem.material_dict_id == None
    ).all()

    print(f"找到 {len(items)} 条 aggregate_id 以 dict: 开头但 material_dict_id 为 None 的数据")

    # 提取字典ID并验证是否存在
    fixed = 0
    not_found = 0
    for item in items:
        try:
            dict_id = int(item.aggregate_id.split(":")[1])
            # 验证字典ID是否存在
            dict_node = db.query(MaterialDict).filter(MaterialDict.id == dict_id).first()
            if dict_node:
                item.material_dict_id = dict_id
                fixed += 1
                if fixed <= 5:
                    print(f"  修复: id={item.id}, aggregate_id={item.aggregate_id}, item_name={item.item_name} -> material_dict_id={dict_id} ({dict_node.name})")
            else:
                not_found += 1
                if not_found <= 5:
                    print(f"  字典ID不存在: id={item.id}, aggregate_id={item.aggregate_id}, dict_id={dict_id}")
        except (ValueError, IndexError) as e:
            print(f"  解析失败: id={item.id}, aggregate_id={item.aggregate_id}, error={e}")

    db.commit()
    print(f"\n修复完成: 成功修复 {fixed} 条，字典ID不存在 {not_found} 条")

    # 验证修复结果
    has_dict = db.query(func.count(BoqItem.id)).filter(
        BoqItem.active == True,
        BoqItem.material_dict_id != None
    ).scalar()
    total = db.query(func.count(BoqItem.id)).filter(BoqItem.active == True).scalar()
    print(f"修复后: 有 material_dict_id 的数据 {has_dict}/{total} ({has_dict/total*100:.1f}%)" if total else "无数据")

finally:
    db.close()
