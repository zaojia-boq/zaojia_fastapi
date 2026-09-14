import gzip, json, os
from collections import Counter

base_dir = r'E:\DEEPSEEK学习\zaojia_fastapi\data\材料价聚类测试文件'

files = [
    'GB50500-2013清单项目_规范提取版_PDF校正.json.gz',
    'GBT50500-2024工程量清单计价.json.gz',
]

for fname in files:
    fpath = os.path.join(base_dir, fname)
    print(f'\n{"="*60}')
    print(f'文件: {fname}')
    print(f'路径: {fpath}')
    print(f'存在: {os.path.exists(fpath)}')
    if os.path.exists(fpath):
        print(f'大小: {os.path.getsize(fpath):,} bytes')
        with gzip.open(fpath, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        print(f'类型: {type(data).__name__}')
        if isinstance(data, list):
            print(f'记录数: {len(data):,}')
            if data:
                print(f'\n字段: {list(data[0].keys())}')
                print(f'\n前3条记录:')
                for item in data[:3]:
                    print(json.dumps(item, ensure_ascii=False, indent=2)[:500])
                    print('---')
        elif isinstance(data, dict):
            print(f'键: {list(data.keys())[:10]}')
            for k in list(data.keys())[:3]:
                v = data[k]
                print(f'  {k}: {type(v).__name__}, len={len(v) if hasattr(v, "__len__") else "N/A"}')
