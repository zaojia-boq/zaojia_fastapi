import gzip, json, os

base_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\data\材料价聚类测试文件'

for fname in ['GB50500-2013清单项目_规范提取版_PDF校正.json.gz', 'GBT50500-2024工程量清单计价.json.gz']:
    fpath = os.path.join(base_dir, fname)
    print(f'\n{"="*60}')
    print(f'文件: {fname}')

    with gzip.open(fpath, 'rt', encoding='utf-8') as f:
        data = json.load(f)

    print(f'sheet_count: {data.get("sheet_count")}')
    sheets = data.get('sheets', {})
    print(f'sheets类型: {type(sheets).__name__}')

    if isinstance(sheets, dict):
        print(f'sheet名称: {list(sheets.keys())}')
        for sheet_name, sheet_data in sheets.items():
            print(f'\n  Sheet: {sheet_name}')
            print(f'  类型: {type(sheet_data).__name__}')
            if isinstance(sheet_data, dict):
                print(f'  键: {list(sheet_data.keys())[:10]}')
                if 'rows' in sheet_data:
                    rows = sheet_data['rows']
                    print(f'  行数: {len(rows)}')
                    if rows:
                        print(f'  第1行: {rows[0]}')
                        print(f'  第2行: {rows[1] if len(rows) > 1 else "N/A"}')
                elif 'data' in sheet_data:
                    d = sheet_data['data']
                    print(f'  data类型: {type(d).__name__}, len={len(d) if hasattr(d, "__len__") else "N/A"}')
                    if isinstance(d, list) and d:
                        print(f'  第1条: {json.dumps(d[0], ensure_ascii=False)[:300]}')
            elif isinstance(sheet_data, list):
                print(f'  行数: {len(sheet_data)}')
                if sheet_data:
                    print(f'  第1行: {sheet_data[0]}')
                    print(f'  第2行: {sheet_data[1] if len(sheet_data) > 1 else "N/A"}')
    elif isinstance(sheets, list):
        print(f'sheets数量: {len(sheets)}')
        if sheets:
            print(f'第1个sheet: {json.dumps(sheets[0], ensure_ascii=False)[:500]}')
