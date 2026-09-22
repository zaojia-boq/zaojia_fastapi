# -*- coding: utf-8 -*-
import pandas as pd

# 读取2024清单安装工程
xlsx_path = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GBT50500-2024工程量清单计价.xlsx'
df = pd.read_excel(xlsx_path, sheet_name='安装工程')

print(f"安装工程总行数：{len(df)}")
print(f"列名：{list(df.columns)}")
print(f"\nF列（分类）统计：")
print(df.iloc[:, 5].value_counts())  # 第6列是F列
