# -*- coding: utf-8 -*-
import pandas as pd

# 读取2013清单 Excel
xlsx_path = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GB50500-2013清单项目_规范提取版_PDF校正.xlsx'

# 读取所有 sheet
xl = pd.ExcelFile(xlsx_path)
print(f"Sheet 列表：{xl.sheet_names}")

# 读取安装工程 sheet
for sheet_name in xl.sheet_names:
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
    print(f"\n=== Sheet: {sheet_name} ===")
    print(f"行数：{len(df)}")
    print(f"列名：{list(df.columns)}")
    print(f"前5行：")
    print(df.head().to_string())
