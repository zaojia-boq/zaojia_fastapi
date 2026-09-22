# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

# 土建二级分类 → 5大类 映射表
# 5大类：电线电缆、管道、钢筋、水泥、混凝土
CATEGORY_TO_5BIG_CONSTRUCTION = {
    # ===== 混凝土类 =====
    "混凝土及钢筋混凝土工程": "混凝土",  # 大部分是混凝土构件

    # ===== 钢筋类 =====
    # 钢筋在混凝土及钢筋混凝土工程里，单独提取

    # ===== 水泥类 =====
    "砌筑工程": "水泥",  # 砂浆/水泥

    # ===== 其他不做单价分析 =====
    "土石方工程": None,
    "地基处理与边坡支护工程": None,
    "桩基工程": None,
    "金属结构工程": None,
    "门窗工程": None,
    "楼地面装饰工程": None,
    "墙、柱面装饰与隔断、幕墙工程": None,
    "天棚工程": None,
    "油漆、涂料、裱糊工程": None,
    "其他装饰工程": None,
    "屋面及防水工程": None,
    "保温、隔热、防腐工程": None,
    "木结构工程": None,
    "拆除工程": None,
    "措施项目": None,
}

db = SessionLocal()
try:
    all_mappings = []
    stats = {}

    # ===== 处理2013清单建筑工程 =====
    print("=== 处理2013清单建筑工程 ===")
    xlsx_2013 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GB50500-2013清单项目_规范提取版_PDF校正.xlsx'
    df_2013 = pd.read_excel(xlsx_2013, sheet_name='建筑工程')
    print(f"读取 {len(df_2013)} 条")

    for _, row in df_2013.iterrows():
        code = str(row.get('项目编码', ''))
        name = str(row.get('项目名称', ''))
        category = str(row.get('二级分类', ''))

        if not code or code == 'nan':
            continue

        # 2013清单是8位编码，补成9位
        code9 = code.ljust(9, '0')

        big5 = CATEGORY_TO_5BIG_CONSTRUCTION.get(category)

        if category not in stats:
            stats[category] = {'total': 0, 'mapped': 0, 'unmapped': 0, 'version': '2013'}
        stats[category]['total'] += 1

        if not big5:
            stats[category]['unmapped'] += 1
            continue

        # 特殊处理：钢筋相关的项目名称
        if '钢筋' in name:
            big5 = '钢筋'
        elif '混凝土' in name:
            big5 = '混凝土'

        mapping = ListMaterialMapping(
            list_item_code=code9,
            list_item_name=name,
            list_version='2013',
            material_code='',
            material_name=name,
            match_type='category_pending',
            similarity=0.0,
        )
        all_mappings.append(mapping)
        stats[category]['mapped'] += 1

    # ===== 处理2024清单建筑工程 =====
    print("\n=== 处理2024清单房屋建筑与装饰工程 ===")
    xlsx_2024 = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GBT50500-2024工程量清单计价.xlsx'
    df_2024 = pd.read_excel(xlsx_2024, sheet_name='房屋建筑与装饰工程')
    print(f"读取 {len(df_2024)} 条")

    for _, row in df_2024.iterrows():
        code = str(row.get('项目编码', ''))
        name = str(row.get('项目名称', ''))
        category = str(row.get('二级分类', ''))

        if not code or code == 'nan':
            continue

        big5 = CATEGORY_TO_5BIG_CONSTRUCTION.get(category)

        key = f"{category}_2024"
        if key not in stats:
            stats[key] = {'total': 0, 'mapped': 0, 'unmapped': 0, 'version': '2024'}
        stats[key]['total'] += 1

        if not big5:
            stats[key]['unmapped'] += 1
            continue

        # 特殊处理：钢筋相关的项目名称
        if '钢筋' in name:
            big5 = '钢筋'
        elif '混凝土' in name:
            big5 = '混凝土'

        mapping = ListMaterialMapping(
            list_item_code=code,
            list_item_name=name,
            list_version='2024',
            material_code='',
            material_name=name,
            match_type='category_pending',
            similarity=0.0,
        )
        all_mappings.append(mapping)
        stats[key]['mapped'] += 1

    print(f"\n生成土建映射：{len(all_mappings)} 条（分类待确认）")
    db.bulk_save_objects(all_mappings)
    db.commit()

    print('\n=== 土建分类统计 ===')
    for category, s in sorted(stats.items(), key=lambda x: -x[1]['total']):
        print(f'  {s["version"]} {category}: {s["mapped"]}/{s["total"]} 已映射')

    print(f'\n总计：{sum(s["mapped"] for s in stats.values())}/{sum(s["total"] for s in stats.values())}')

finally:
    db.close()
