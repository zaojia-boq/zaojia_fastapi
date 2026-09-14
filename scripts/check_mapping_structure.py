import json

# 检查匹配结果结构
mapping_path = r'E:\DEEPSEEK学习\zaojia_fastapi\deliverables\list_material_mapping\list_material_mapping_v2.json'
with open(mapping_path, 'r', encoding='utf-8') as f:
    mapping = json.load(f)

print(f'匹配映射记录数: {len(mapping)}')
print('\n前3条记录:')
for item in mapping[:3]:
    print(json.dumps(item, ensure_ascii=False, indent=2))
    print('---')

# 检查字段
if mapping:
    print('\n所有字段:')
    for key in mapping[0].keys():
        print(f'  {key}: {type(mapping[0][key]).__name__}')
