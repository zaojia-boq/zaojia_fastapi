# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

# 2013清单二级分类 → 5大类 映射表
# 5大类：电线电缆、管道、钢筋、水泥、混凝土
CATEGORY_MAP_2013 = {
    # ===== 土建工程 =====
    # 混凝土类
    "混凝土及钢筋混凝土工程": "混凝土",  # 大部分是混凝土构件

    # 钢筋类（单独提取）
    # 钢筋相关项目名称单独提取

    # 水泥类
    "砌筑工程": "水泥",

    # ===== 安装工程 =====
    # 电线电缆类
    "电气设备安装工程": "电线电缆",
    "通信设备及线路工程": "电线电缆",
    "建筑智能化工程": "电线电缆",
    "建筑智能化系统设备安装工程": "电线电缆",

    # 管道类
    "给排水、采暖、燃气工程": "管道",
    "热力设备安装工程": "管道",
    "通风空调工程": "管道",
    "消防工程": "管道",

    # ===== 其他不做单价分析 =====
    "措施项目": None,
    "其他装饰工程": None,
    "门窗工程": None,
    "楼地面装饰工程": None,
    "拆除工程": None,
    "油漆、涂料、裱糊工程": None,
    "墙、柱面装饰与隔断、幕墙工程": None,
    "金属结构工程": None,
    "地基处理与边坡支护工程": None,
    "屋面及防水工程": None,
    "保温、隔热、防腐工程": None,
    "土石方工程": None,
    "桩基工程": None,
    "天棚工程": None,
    "木结构工程": None,
    "机械设备安装工程": None,
    "刷油、防腐蚀、绝热工程": None,
    "自动化控制仪表安装工程": None,
    "静置设备与工艺金属结构制作安装工程": None,
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

        big5 = CATEGORY_MAP_2013.get(category)

        if category not in stats:
            stats[category] = {'total': 0, 'mapped': 0, 'unmapped': 0}
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
            material_name=big5,
            match_type='category_mapped',
            similarity=80.0,
        )
        all_mappings.append(mapping)
        stats[category]['mapped'] += 1

    # ===== 处理2013清单安装工程 =====
    print("\n=== 处理2013清单安装工程 ===")
    df_2013_install = pd.read_excel(xlsx_2013, sheet_name='安装工程')
    print(f"读取 {len(df_2013_install)} 条")

    for _, row in df_2013_install.iterrows():
        code = str(row.get('项目编码', ''))
        name = str(row.get('项目名称', ''))
        category = str(row.get('二级分类', ''))

        if not code or code == 'nan':
            continue

        # 2013清单是8位编码，补成9位
        code9 = code.ljust(9, '0')

        big5 = CATEGORY_MAP_2013.get(category)

        key = f"{category}_install"
        if key not in stats:
            stats[key] = {'total': 0, 'mapped': 0, 'unmapped': 0}
        stats[key]['total'] += 1

        if not big5:
            stats[key]['unmapped'] += 1
            continue

        mapping = ListMaterialMapping(
            list_item_code=code9,
            list_item_name=name,
            list_version='2013',
            material_code='',
            material_name=big5,
            match_type='category_mapped',
            similarity=80.0,
        )
        all_mappings.append(mapping)
        stats[key]['mapped'] += 1

    print(f"\n生成2013映射：{len(all_mappings)} 条")

    # 把2013映射追加到现有2024映射后面
    db.bulk_save_objects(all_mappings)
    db.commit()
    print("已插入到数据库")

    print('\n=== 分类统计 ===')
    for category, s in sorted(stats.items(), key=lambda x: -x[1]['total']):
        if s['mapped'] > 0:
            print(f'  {category}: {s["mapped"]}/{s["total"]} 已映射')

    # 统计总数
    total_count = db.query(ListMaterialMapping).count()
    print(f'\n数据库总映射数：{total_count} 条')

    # 按版本统计
    print('\n=== 按版本统计 ===')
    from sqlalchemy import func
    version_stats = db.query(ListMaterialMapping.list_version, func.count(ListMaterialMapping.id)).group_by(ListMaterialMapping.list_version).all()
    for version, cnt in version_stats:
        print(f'  {version}: {cnt} 条')

finally:
    db.close()
