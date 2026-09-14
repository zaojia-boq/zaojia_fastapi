"""检查材料字典表中特定名称是否存在，并通过名称匹配修复material_dict_id"""
import sys
sys.path.insert(0, r'E:\DEEPSEEK学习\zaojia_fastapi')

from app.db import SessionLocal
from app.models.boq_item import BoqItem
from app.models.material_dict import MaterialDict
from sqlalchemy import func

db = SessionLocal()

try:
    # 1. 收集所有 dict:xxx 格式的 aggregate_id 及其对应的 item_name
    items = db.query(BoqItem).filter(
        BoqItem.active == True,
        BoqItem.aggregate_id.like('dict:%')
    ).all()

    print(f"共有 {len(items)} 条 aggregate_id 以 dict: 开头的数据")

    # 收集旧ID -> item_name 映射
    old_id_names = {}
    for item in items:
        try:
            old_id = int(item.aggregate_id.split(":")[1])
            if old_id not in old_id_names:
                old_id_names[old_id] = set()
            old_id_names[old_id].add(item.item_name or "")
        except (ValueError, IndexError):
            pass

    print(f"\n涉及 {len(old_id_names)} 个旧字典ID:")
    for old_id, names in sorted(old_id_names.items()):
        print(f"  旧ID {old_id}: {list(names)[:3]}")

    # 2. 在新材料字典表中按名称搜索
    print("\n在新材料字典表中按名称搜索:")
    name_to_new_id = {}
    all_names = set()
    for names in old_id_names.values():
        all_names.update(names)

    for name in all_names:
        if not name:
            continue
        # 精确匹配
        nodes = db.query(MaterialDict).filter(MaterialDict.name == name).all()
        if nodes:
            # 取第一个（通常是l4材料名称层）
            # 优先选择 level='l4' 的节点
            l4_nodes = [n for n in nodes if n.level == 'l4']
            target = l4_nodes[0] if l4_nodes else nodes[0]
            name_to_new_id[name] = target.id
            print(f"  '{name}' -> 新ID {target.id} (level={target.level}, 找到{len(nodes)}个匹配)")
        else:
            print(f"  '{name}' -> 未找到精确匹配")

    # 3. 修复数据：通过 item_name 匹配新字典ID
    fixed = 0
    not_fixed = 0
    for item in items:
        name = item.item_name or ""
        if name in name_to_new_id:
            new_id = name_to_new_id[name]
            item.material_dict_id = new_id
            item.aggregate_id = f"dict:{new_id}"
            # 重新计算 match_key
            from data.gb_code import compute_match_key
            match_key, source = compute_match_key(
                item_code=item.item_code or "",
                item_name=item.item_name or "",
                item_feature=item.item_feature or "",
                unit_std=item.unit_std or "",
                std_name=item.std_name or "",
                std_spec=item.std_spec or "",
                material_dict_id=new_id,
                item_code_version=item.item_code_version or "unknown",
            )
            item.match_key = match_key
            item.match_key_source = source
            fixed += 1
        else:
            # 名称未匹配，将 aggregate_id 改为 raw 格式
            not_fixed += 1
            if not_fixed <= 5:
                print(f"  未匹配: id={item.id}, item_name={item.item_name}, aggregate_id={item.aggregate_id}")

    db.commit()
    print(f"\n修复完成: 成功修复 {fixed} 条，未匹配 {not_fixed} 条")

    # 4. 验证修复结果
    has_dict = db.query(func.count(BoqItem.id)).filter(
        BoqItem.active == True,
        BoqItem.material_dict_id != None
    ).scalar()
    total = db.query(func.count(BoqItem.id)).filter(BoqItem.active == True).scalar()
    print(f"修复后: 有 material_dict_id 的数据 {has_dict}/{total} ({has_dict/total*100:.1f}%)" if total else "无数据")

    # 5. 查看 match_key_source 分布
    print("\nmatch_key_source 分布:")
    source_rows = db.query(
        BoqItem.match_key_source,
        func.count(BoqItem.id)
    ).filter(BoqItem.active == True).group_by(BoqItem.match_key_source).all()
    for source, cnt in source_rows:
        print(f"  {source}: {cnt}")

finally:
    db.close()
