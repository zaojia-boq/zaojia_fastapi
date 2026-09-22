# -*- coding: utf-8 -*-
"""根据分类重新生成 list_material_mapping 映射表。

规则：
- 清空现有映射
- 从 2024 清单规范 Excel 读取所有清单项
- 按二级分类映射到 5 大类
- 为每个 9 位编码生成映射记录
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping
from data.category_mapping import CATEGORY_TO_5BIG, CODE_PREFIX_TO_CATEGORY_2024, CODE_PREFIX_TO_CATEGORY_2013


def rebuild_mapping():
    db = SessionLocal()
    try:
        # 1. 清空现有映射
        print("清空现有映射...")
        deleted = db.query(ListMaterialMapping).delete()
        db.commit()
        print(f"已删除 {deleted} 条旧映射")

        # 2. 读取 2024 清单分类映射表
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "deliverables",
            "list_material_mapping",
            "2024清单_编码名称分类映射表.csv"
        )
        df = pd.read_csv(csv_path)
        print(f"\n读取 2024 清单数据：{len(df)} 条")

        # 3. 按分类重新生成映射
        new_mappings = []
        category_stats = {}

        for _, row in df.iterrows():
            code9 = str(row.get('清单编码(9位)', ''))
            name = str(row.get('项目名称', ''))
            category = str(row.get('二级分类', ''))

            if not code9 or code9 == 'nan':
                continue

            # 根据分类确定 5 大类
            5big = CATEGORY_TO_5BIG.get(category)

            # 统计
            if category not in category_stats:
                category_stats[category] = {'total': 0, 'mapped': 0, 'unmapped': 0}
            category_stats[category]['total'] += 1

            if not 5big:
                category_stats[category]['unmapped'] += 1
                continue

            # 生成映射记录
            # 注意：这里只是标记分类，材料名称后续由用户手动确认
            mapping = ListMaterialMapping(
                list_item_code=code9,
                list_item_name=name,
                list_version='2024',
                material_name=None,  # 待用户手动确认
                match_type='category_pending',  # 分类待确认
                similarity=0.0,
            )
            new_mappings.append(mapping)
            category_stats[category]['mapped'] += 1

        # 4. 批量插入
        print(f"\n生成新映射：{len(new_mappings)} 条（分类待确认）")
        db.bulk_save_objects(new_mappings)
        db.commit()

        # 5. 统计输出
        print(f"\n=== 分类统计 ===")
        print(f"{'分类':<25} {'总数':>8} {'已映射':>8} {'未映射':>8}")
        print("-" * 55)
        for category, stats in sorted(category_stats.items(), key=lambda x: -x[1]['total']):
            print(f"{category:<25} {stats['total']:>8} {stats['mapped']:>8} {stats['unmapped']:>8}")

        print(f"\n=== 总计 ===")
        print(f"总清单项：{sum(s['total'] for s in category_stats.values())}")
        print(f"已映射（分类）：{sum(s['mapped'] for s in category_stats.values())}")
        print(f"未映射：{sum(s['unmapped'] for s in category_stats.values())}")

    finally:
        db.close()


if __name__ == "__main__":
    rebuild_mapping()



