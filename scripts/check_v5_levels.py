import gzip, json
from collections import Counter

with gzip.open(r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\material_dict_cleaned\zhongjian_material_dict_v5.json.gz', 'rt', encoding='utf-8') as f:
    data = json.load(f)

print(f'总记录数: {len(data):,}')
level_counter = Counter(item['层级'] for item in data)
print('\n各层级记录数:')
for level in sorted(level_counter.keys()):
    print(f'  层级{level}: {level_counter[level]:,}')

print('\n前5条记录示例:')
for item in data[:5]:
    print(f'  编码={item["编码"]}, 层级={item["层级"]}, 名称={item["名称"]}, 父编码={item.get("父编码","")}, 单位={item.get("单位","")}')

print('\n层级1节点（前10）:')
l1 = [item for item in data if item['层级'] == 1]
for item in l1[:10]:
    print(f'  {item["编码"]}: {item["名称"]}')
print(f'  ... 共 {len(l1)} 个')

print('\n层级5叶子节点示例（前5）:')
l5 = [item for item in data if item['层级'] == 5]
for item in l5[:5]:
    print(f'  编码={item["编码"]}, 名称={item["名称"]}, 规格={item.get("规格","")}, 单位={item.get("单位","")}, 材质={item.get("材质","")}')
print(f'  ... 共 {len(l5):,} 个')
