# -*- coding: utf-8 -*-
"""
级联补全无编码节点的五级编码（v2：防唯一约束冲突）。
处理顺序：l3 → l4 → l5，多轮级联。
"""
import sys
sys.path.insert(0, r"E:\DEEPSEEK学习\zaojia_fastapi")
from app.db import SessionLocal
from app.models.material_dict import MaterialDict
from sqlalchemy import func

DIGIT_MAP = {"l1": 3, "l2": 2, "l3": 2, "l4": 3, "l5": 4}


def generate_code_for_node(db, node):
    """为单个节点生成编码，确保全局唯一。返回新编码或 None。"""
    level = node.level
    digits = DIGIT_MAP[level]

    if level == "l1":
        prefix = "I"
        max_node = db.query(MaterialDict).filter(
            MaterialDict.level == "l1",
            MaterialDict.code.isnot(None),
            MaterialDict.code != "",
        ).order_by(MaterialDict.code.desc()).first()
        max_seq = int(max_node.code[1:]) if max_node and max_node.code else 0
        candidate = max_seq + 1
        while True:
            code = f"{prefix}{candidate:0{digits}d}"
            exists = db.query(MaterialDict.id).filter(MaterialDict.code == code).first()
            if not exists:
                return code
            candidate += 1

    if not node.parent_id:
        return None
    parent = db.query(MaterialDict).filter(MaterialDict.id == node.parent_id).first()
    if not parent or not parent.code:
        return None

    prefix = parent.code
    # 查询同父级下所有已有编码，提取最大序号
    siblings = db.query(MaterialDict.code).filter(
        MaterialDict.parent_id == node.parent_id,
        MaterialDict.code.isnot(None),
        MaterialDict.code != "",
    ).all()
    max_seq = 0
    for (sib_code,) in siblings:
        if sib_code and sib_code.startswith(prefix):
            try:
                suffix = sib_code[len(prefix):]
                seq = int(suffix)
                if seq > max_seq:
                    max_seq = seq
            except (ValueError, IndexError):
                pass

    # 从 max_seq+1 开始，找到全局唯一的编码
    candidate = max_seq + 1
    while True:
        code = f"{prefix}{candidate:0{digits}d}"
        exists = db.query(MaterialDict.id).filter(MaterialDict.code == code).first()
        if not exists:
            return code
        candidate += 1


def backfill_level(db, level):
    """补全指定层级的所有无编码节点，逐条提交。"""
    nodes = db.query(MaterialDict).filter(
        MaterialDict.level == level,
        (MaterialDict.code.is_(None)) | (MaterialDict.code == "")
    ).order_by(MaterialDict.parent_id, MaterialDict.id).all()

    fixed = 0
    skipped = 0
    for node in nodes:
        new_code = generate_code_for_node(db, node)
        if new_code:
            node.code = new_code
            db.commit()  # 逐条提交，避免批量冲突
            fixed += 1
        else:
            skipped += 1
    return fixed, skipped, len(nodes)


def main():
    with SessionLocal() as db:
        total_no_code = db.query(func.count(MaterialDict.id)).filter(
            (MaterialDict.code.is_(None)) | (MaterialDict.code == "")
        ).scalar()
        print(f"补全前无编码节点: {total_no_code:,} 条")

        for round_num in range(1, 5):
            print(f"\n=== 第 {round_num} 轮级联补全 ===")
            total_fixed_this_round = 0
            for level in ["l3", "l4", "l5"]:
                fixed, skipped, total = backfill_level(db, level)
                total_fixed_this_round += fixed
                if total > 0:
                    print(f"  {level}: 共{total}条无编码, 补全{fixed}条, 跳过{skipped}条")
            if total_fixed_this_round == 0:
                print("  本轮无新增补全，停止")
                break

        total_no_code_after = db.query(func.count(MaterialDict.id)).filter(
            (MaterialDict.code.is_(None)) | (MaterialDict.code == "")
        ).scalar()
        total = db.query(func.count(MaterialDict.id)).scalar()
        print(f"\n=== 补全结果 ===")
        print(f"总节点数: {total:,}")
        print(f"补全前无编码: {total_no_code:,}")
        print(f"补全后无编码: {total_no_code_after:,}")
        print(f"本次补全: {total_no_code - total_no_code_after:,} 条")
        print(f"编码覆盖率: {(total - total_no_code_after) / total * 100:.2f}%")

        # 按层级统计
        print(f"\n=== 补全后各层级编码情况 ===")
        for level in ["l1", "l2", "l3", "l4", "l5"]:
            total_lv = db.query(func.count(MaterialDict.id)).filter(
                MaterialDict.level == level).scalar()
            no_code_lv = db.query(func.count(MaterialDict.id)).filter(
                MaterialDict.level == level,
                (MaterialDict.code.is_(None)) | (MaterialDict.code == "")).scalar()
            print(f"  {level}: 总{total_lv:,}条, 无编码{no_code_lv}条")

        if total_no_code_after > 0:
            print(f"\n剩余无编码节点样本:")
            remaining = db.query(MaterialDict).filter(
                (MaterialDict.code.is_(None)) | (MaterialDict.code == "")
            ).limit(10).all()
            for n in remaining:
                parent_info = "无父级"
                if n.parent_id:
                    p = db.query(MaterialDict).filter(MaterialDict.id == n.parent_id).first()
                    parent_info = f"父级id={n.parent_id}, 父编码={p.code if p else '?'}, 父层级={p.level if p else '?'}"
                print(f"  id={n.id}, level={n.level}, name={n.name}, {parent_info}")


if __name__ == "__main__":
    main()
