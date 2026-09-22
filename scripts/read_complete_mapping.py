# -*- coding: utf-8 -*-
import pandas as pd

# 读取完整映射表
xlsx_path = 'deliverables/list_material_mapping/映射表_完整_2013+2024.xlsx'
df = pd.read_excel(xlsx_path)

print(f"总行数：{len(df)}")
print(f"列名：{list(df.columns)}")
print(f"\n前5行：")
print(df.head().to_string())

print(f"\n按版本统计：")
print(df['清单版本'].value_counts() if '清单版本' in df.columns else df['list_version'].value_counts())

print(f"\n按映射大类统计：")
if '映射大类' in df.columns:
    print(df['映射大类'].value_counts())
else:
    print(df['material_name'].value_counts())

# 看看2013钢筋有多少
print(f"\n2013钢筋：")
version_col = '清单版本' if '清单版本' in df.columns else 'list_version'
cat_col = '映射大类' if '映射大类' in df.columns else 'material_name'

rebar_2013 = df[(df[version_col] == '2013') & (df[cat_col] == '钢筋')]
print(f"  数量：{len(rebar_2013)}")
print(rebar_2013.to_string())
