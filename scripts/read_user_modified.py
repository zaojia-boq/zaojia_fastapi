# -*- coding: utf-8 -*-
import pandas as pd

# 读取用户手动修改后的文件
xlsx_path = 'deliverables/list_material_mapping/映射表_手动修改版.xlsx'
df = pd.read_excel(xlsx_path)

print(f"总行数：{len(df)}")
print(f"列名：{list(df.columns)}")
print(f"\n按版本统计：")
print(df['清单版本'].value_counts())

print(f"\n按映射大类统计：")
print(df['映射大类'].value_counts())

# 看看2013钢筋有多少
print(f"\n2013钢筋：")
rebar_2013 = df[(df['清单版本'] == '2013') & (df['映射大类'] == '钢筋')]
print(f"  数量：{len(rebar_2013)}")
print(rebar_2013[['清单编码', '项目名称', '映射大类']].to_string())
