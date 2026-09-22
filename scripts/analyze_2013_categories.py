# -*- coding: utf-8 -*-
import pandas as pd

# 读取2013清单建筑工程
xlsx_2013 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GB50500-2013清单项目_规范提取版_PDF校正.xlsx'
df_2013 = pd.read_excel(xlsx_2013, sheet_name='建筑工程')

print(f"2013清单建筑工程总行数：{len(df_2013)}")
print(f"列名：{list(df_2013.columns)}")
print(f"\n二级分类统计：")
print(df_2013['二级分类'].value_counts())

# 读取2013清单安装工程
df_2013_install = pd.read_excel(xlsx_2013, sheet_name='安装工程')
print(f"\n2013清单安装工程总行数：{len(df_2013_install)}")
print(f"二级分类统计：")
print(df_2013_install['二级分类'].value_counts())
