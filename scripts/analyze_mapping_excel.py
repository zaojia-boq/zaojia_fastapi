# -*- coding: utf-8 -*-
import pandas as pd

xlsx_path = 'deliverables/list_material_mapping/2024清单映射.xlsx'

# 读取 Excel
df = pd.read_excel(xlsx_path)
print(f"总行数：{len(df)}")
print(f"列名：{list(df.columns)}")
print(f"\n前10行：")
print(df.head(10).to_string())

print(f"\nF列（分类）统计：")
print(df.iloc[:, 5].value_counts())  # 第6列是F列
