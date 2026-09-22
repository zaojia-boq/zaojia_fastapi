# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

# 读取用户修改后的 Excel
xlsx_path = 'deliverables/list_material_mapping/映射表_5大类_F列分类映射.xlsx'
df = pd.read_excel(xlsx_path)
print(f"读取 {len(df)} 条映射")
print(f"列名：{list(df.columns)}")
print(f"\n前5行：")
print(df.head().to_string())

db = SessionLocal()
try:
    # 清空旧映射
    db.query(ListMaterialMapping).delete()
    db.commit()
    print("\n已清空旧映射")

    # 插入新映射
    new_mappings = []
    for _, row in df.iterrows():
        mapping = ListMaterialMapping(
            list_version=str(row.get('清单版本', '2024')),
            list_item_code=str(row.get('清单编码', '')),
            list_item_name=str(row.get('项目名称', '')),
            material_code=str(row.get('映射材料编码', '')),
            material_name=str(row.get('映射大类', row.get('映射材料名称', ''))),
            match_type=str(row.get('匹配类型', 'category_mapped')),
            similarity=float(row.get('相似度', 80.0)),
        )
        new_mappings.append(mapping)

    db.bulk_save_objects(new_mappings)
    db.commit()
    print(f"已插入 {len(new_mappings)} 条映射")

    # 统计
    print("\n=== 映射统计 ===")
    material_counts = {}
    for m in new_mappings:
        material_counts[m.material_name] = material_counts.get(m.material_name, 0) + 1

    for material, count in sorted(material_counts.items(), key=lambda x: -x[1]):
        print(f"  {material}: {count} 条")

finally:
    db.close()
