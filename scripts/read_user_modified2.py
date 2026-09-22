# -*- coding: utf-8 -*-
import pandas as pd

# 读取用户手动修改后的文件
xlsx_path = 'deliverables/list_material_mapping/映射表_手动修改版.xlsx'
df = pd.read_excel(xlsx_path)

print(f"总行数：{len(df)}")
print(f"列名：{list(df.columns)}")
print(f"\n前5行：")
print(df.head().to_string())

print(f"\n按 list_version 统计：")
print(df['list_version'].value_counts())

print(f"\n按 material_name 统计：")
print(df['material_name'].value_counts())

# 看看2013钢筋有多少
print(f"\n2013钢筋：")
rebar_2013 = df[(df['list_version'] == '2013') & (df['material_name'] == '钢筋')]
print(f"  数量：{len(rebar_2013)}")
print(rebar_2013[['list_item_code', 'list_item_name', 'material_name']].to_string())
