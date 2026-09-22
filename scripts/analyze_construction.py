# -*- coding: utf-8 -*-
import pandas as pd

# 读取2013清单建筑工程
xlsx_2013 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GB50500-2013清单项目_规范提取版_PDF校正.xlsx'
df_2013 = pd.read_excel(xlsx_2013, sheet_name='建筑工程')

print(f"=== 2013清单建筑工程 ===")
print(f"总行数：{len(df_2013)}")
print(f"\n二级分类统计：")
print(df_2013['二级分类'].value_counts())

# 读取2024清单建筑工程
xlsx_2024 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GBT50500-2024工程量清单计价.xlsx'
df_2024 = pd.read_excel(xlsx_2024, sheet_name='房屋建筑与装饰工程')

print(f"\n=== 2024清单房屋建筑与装饰工程 ===")
print(f"总行数：{len(df_2024)}")
print(f"列名：{list(df_2024.columns)}")
print(f"\n二级分类统计：")
print(df_2024.iloc[:, 1].value_counts())  # 第二列是二级分类
