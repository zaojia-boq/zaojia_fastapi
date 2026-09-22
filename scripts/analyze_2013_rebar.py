# -*- coding: utf-8 -*-
import pandas as pd

xlsx_2013 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GB50500-2013清单项目_规范提取版_PDF校正.xlsx'
df_2013 = pd.read_excel(xlsx_2013, sheet_name='建筑工程')

# 找钢筋相关的项目
rebar_items = df_2013[df_2013['项目名称'].str.contains('钢筋|螺栓|铁件', na=False)]
print(f"2013清单建筑工程中钢筋相关项目：{len(rebar_items)} 条")
print(rebar_items[['项目编码', '项目名称', '二级分类']].to_string())

# 看看混凝土及钢筋混凝土工程里的所有项目
concrete_items = df_2013[df_2013['二级分类'] == '混凝土及钢筋混凝土工程']
print(f"\n混凝土及钢筋混凝土工程总数：{len(concrete_items)} 条")
print(concrete_items[['项目编码', '项目名称']].to_string())
