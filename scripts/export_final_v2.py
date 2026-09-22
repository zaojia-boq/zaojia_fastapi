# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

db = SessionLocal()
try:
    mappings = db.query(ListMaterialMapping).order_by(ListMaterialMapping.material_name, ListMaterialMapping.list_item_code).all()
    print(f"导出 {len(mappings)} 条映射")

    data = []
    for m in mappings:
        data.append({
            '清单版本': m.list_version,
            '清单编码': m.list_item_code,
            '项目名称': m.list_item_name,
            '映射大类': m.material_name,
            '匹配类型': m.match_type,
            '相似度': m.similarity,
        })

    df = pd.DataFrame(data)
    output_path = 'deliverables/list_material_mapping/映射表_5大类_F列分类映射.xlsx'
    df.to_excel(output_path, index=False)
    print(f"已导出到：{output_path}")

    print("\n=== 按映射大类统计 ===")
    print(df['映射大类'].value_counts())

    print("\n=== 按匹配类型统计 ===")
    print(df['匹配类型'].value_counts())

finally:
    db.close()
