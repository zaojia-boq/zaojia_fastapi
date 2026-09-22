# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

# ===== 土建 F列分类 → 映射材料名称 =====
CONSTRUCTION_CATEGORY_MAP = {
    "现浇混凝土构件": "混凝土",
    "装配式混凝土构件": "混凝土",
    "预制混凝土构件": "混凝土",
    "垫层": "混凝土",
    "钢筋及螺栓、铁件": "钢筋",
    "砖砌体": "水泥",
    "石砌体": "水泥",
    "砌块砌体": "水泥",
}

# ===== 安装工程 F列分类 → 映射材料名称 =====
INSTALL_CATEGORY_MAP = {
    # ===== 电线电缆类 =====
    "电力电缆": "电线电缆",
    "控制电缆": "电线电缆",
    "弱电电缆": "电线电缆",
    "通信配线": "电线电缆",
    "电线": "电线电缆",
    "母线": "电线电缆",

    # ===== 管道类 =====
    "工业管道": "管道",
    "工业管件": "管道",
    "通风管道": "管道",
    "阀门": "管道",
    "阀门管件": "管道",
    "管道": "管道",
    "通风管道阀门": "管道",
    "消防管道": "管道",
    "仪表管路": "管道",
    "通信管道": "管道",
    "管道附件": "管道",

    # ===== 其他不做单价分析 =====
    "锅炉设备": None,
    "消防设备": None,
    "有线通信设备": None,
    # ... 其他设备类都不做
}

db = SessionLocal()
try:
    all_mappings = []
    stats = {'混凝土': 0, '钢筋': 0, '水泥': 0, '电线电缆': 0, '管道': 0}

    # ===== 处理土建工程 =====
    print("=== 处理土建工程 ===")
    xlsx_construction = 'deliverables/list_material_mapping/2024清单映射.xlsx'
    df_constr = pd.read_excel(xlsx_construction)
    print(f"读取 {len(df_constr)} 条")

    for _, row in df_constr.iterrows():
        code = str(row.get('项目编码', ''))
        name = str(row.get('项目名称', ''))
        category = str(row.get('分类', ''))

        if not code or code == 'nan':
            continue

        material_name = CONSTRUCTION_CATEGORY_MAP.get(category)

        if material_name:
            mapping = ListMaterialMapping(
                list_item_code=code,
                list_item_name=name,
                list_version='2024',
                material_code='',
                material_name=material_name,
                match_type='category_mapped',
                similarity=80.0,
            )
            all_mappings.append(mapping)
            stats[material_name] += 1

    # ===== 处理安装工程 =====
    print("\n=== 处理安装工程 ===")
    xlsx_install = r'F:\360MoveData\Users\ht835\Desktop\测试文件\GBT50500-2024工程量清单计价.xlsx'
    df_install = pd.read_excel(xlsx_install, sheet_name='安装工程')
    print(f"读取 {len(df_install)} 条")

    for _, row in df_install.iterrows():
        code = str(row.get('项目编码', ''))
        name = str(row.get('项目名称', ''))
        category = str(row.get('分类', ''))

        if not code or code == 'nan':
            continue

        material_name = INSTALL_CATEGORY_MAP.get(category)

        if material_name:
            mapping = ListMaterialMapping(
                list_item_code=code,
                list_item_name=name,
                list_version='2024',
                material_code='',
                material_name=material_name,
                match_type='category_mapped',
                similarity=80.0,
            )
            all_mappings.append(mapping)
            stats[material_name] += 1

    print(f"\n生成映射：{len(all_mappings)} 条（按F列分类）")

    # 清空旧映射，插入新映射
    db.query(ListMaterialMapping).delete()
    db.commit()
    print("已清空旧映射")

    db.bulk_save_objects(all_mappings)
    db.commit()
    print("已插入新映射")

    print("\n=== 映射统计 ===")
    for material, count in stats.items():
        print(f"  {material}: {count} 条")

    print(f"\n总计：{sum(stats.values())} 条")

finally:
    db.close()
