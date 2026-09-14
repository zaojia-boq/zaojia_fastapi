import gzip, json, os

fpath = r'E:\DEEPSEEK学习\zaojia_fastapi\data\材料价聚类测试文件\GBT50500-2024工程量清单计价.json.gz'

with gzip.open(fpath, 'rt', encoding='utf-8') as f:
    data = json.load(f)

sheets = data['sheets']
print(f'共 {len(sheets)} 个sheet:')
for i, sheet in enumerate(sheets):
    print(f'  [{i}] {sheet["name"]} (rows={sheet["row_count"]})')

# 检查第2个及以后的sheet
for i in range(1, min(3, len(sheets))):
    sheet = sheets[i]
    print(f'\n{"="*60}')
    print(f'Sheet [{i}]: {sheet["name"]}')
    rows = sheet['rows']
    print(f'行数: {len(rows)}')
    if rows:
        print(f'表头: {rows[0]}')
        print(f'第1行数据: {rows[1] if len(rows) > 1 else "N/A"}')
        print(f'第2行数据: {rows[2] if len(rows) > 2 else "N/A"}')

# 统计2024版所有清单项目数
print(f'\n{"="*60}')
print('2024版清单项目统计:')
total_items = 0
for sheet in sheets[1:]:  # 跳过总目录
    rows = sheet['rows']
    if len(rows) > 1:
        # 假设第一行是表头，统计有项目编码的行
        item_count = 0
        for row in rows[1:]:
            if row and len(row) > 3 and row[3]:  # 项目编码在第4列
                item_count += 1
        print(f'  {sheet["name"]}: {item_count} 条')
        total_items += item_count
print(f'  总计: {total_items} 条')

# 2013版统计
print(f'\n{"="*60}')
print('2013版清单项目统计:')
fpath2013 = r'E:\DEEPSEEK学习\zaojia_fastapi\data\材料价聚类测试文件\GB50500-2013清单项目_规范提取版_PDF校正.json.gz'
with gzip.open(fpath2013, 'rt', encoding='utf-8') as f:
    data2013 = json.load(f)

total_2013 = 0
for sheet in data2013['sheets']:
    rows = sheet['rows']
    if len(rows) > 1:
        item_count = 0
        for row in rows[1:]:
            if row and len(row) > 3 and row[3]:  # 项目编码在第4列
                item_count += 1
        print(f'  {sheet["name"]}: {item_count} 条')
        total_2013 += item_count
print(f'  总计: {total_2013} 条')
