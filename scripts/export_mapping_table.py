# -*- coding: utf-8 -*-
"""导出 list_material_mapping 映射表为 Excel，供手动修改。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping
from app.models.material_dict import MaterialDict

def export_mapping_table():
    db = SessionLocal()
    try:
        # 读取所有映射
        mappings = db.query(ListMaterialMapping).all()
        print(f"总映射条数: {len(mappings)}")

        # 构建 DataFrame
        rows = []
        for m in mappings:
            rows.append({
                "id": m.id,
                "list_item_code": m.list_item_code or "",
                "list_item_name": m.list_item_name or "",
                "list_version": m.list_version or "",
                "material_code": m.material_code or "",
                "material_name": m.material_name or "",
                "match_type": m.match_type or "",
                "similarity": round(m.similarity, 2) if m.similarity else "",
                "biz_id": m.biz_id or "",
                "create_date": str(m.create_date) if m.create_date else "",
            })

        df = pd.DataFrame(rows)

        # 导出 Excel
        output_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "deliverables",
            "list_material_mapping",
            "映射表_手动修改版.xlsx"
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='映射表', index=False)

            # 调整列宽
            worksheet = writer.sheets['映射表']
            column_widths = {
                'A': 6,   # id
                'B': 16,  # list_item_code
                'C': 40,  # list_item_name
                'D': 10,  # list_item_version
                'E': 12,  # material_dict_id
                'F': 30,  # material_name
                'G': 12,  # match_type
                'H': 10,  # confidence
                'I': 10,  # is_correct
                'J': 30,  # note
            }
            for col, width in column_widths.items():
                worksheet.column_dimensions[col].width = width

        print(f"导出完成: {output_path}")
        print(f"总行数: {len(df)}")
        print(f"按匹配类型统计:")
        print(df['match_type'].value_counts())
        print(f"\n按版本统计:")
        print(df['list_version'].value_counts())

    finally:
        db.close()

if __name__ == "__main__":
    export_mapping_table()
