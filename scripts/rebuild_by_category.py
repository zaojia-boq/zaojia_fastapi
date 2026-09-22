# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')

import pandas as pd
from app.db import SessionLocal
from app.models.list_material_mapping import ListMaterialMapping

# F列分类 → 映射材料名称
CATEGORY_TO_MATERIAL = {
    # ===== 混凝土类 =====
    "现浇混凝土构件": "混凝土",
    "装配式混凝土构件": "混凝土",
    "预制混凝土构件": "混凝土",
    "垫层": "混凝土",

    # ===== 钢筋类 =====
    "钢筋及螺栓、铁件": "钢筋",

    # ===== 砌筑类 =====
    "砖砌体": "水泥",
    "石砌体": "水泥",
    "砌块砌体": "水泥",

    # ===== 其他不做单价分析 =====
    "金属结构": None,
    "门": None,
    "窗": None,
    "模板": None,
    "地面面层": None,
    "基坑与边坡支护": None,
    "措施项目": None,
    "天棚装饰": None,
    "土石方": None,
    "墙、柱饰面": None,
    "地基处理": None,
    "零星装饰项目": None,
    "屋面防水": None,
    "幕墙工程": None,
    "屋面": None,
    "木结构": None,
    "楼梯面层": None,
    "踢脚线": None,
    "灌注桩": None,
    "防腐面层": None,
    "墙、柱面抹灰": None,
    "保温、隔热": None,
    "招牌、灯箱": None,
    "台阶装饰": None,
    "金属制品": None,
    "预制桩": None,
    "其他防腐": None,
    "地面防水": None,
    "栏杆": None,
    "浴厕配件": None,
    "墙、柱面面层": None,
    "装饰柜、架、台": None,
    "墙面防水": None,
    "地面找平层": None,
    "隔墙、隔断": None,
    "零星抹灰": None,
    "基础防水": None,
    "零星块料面层": None,
    "墙板": None,
    "暖气罩": None,
    "装饰板雨篷": None,
    "成品装饰柱": None,
    "金属旗杆": None,
}

db = SessionLocal()
try:
    # 读取2024清单 Excel
    xlsx_path = 'deliverables/list_material_mapping/2024清单映射.xlsx'
    df = pd.read_excel(xlsx_path)
    print(f"读取 {len(df)} 条")

    new_mappings = []
    category_stats = {}

    for _, row in df.iterrows():
        code = str(row.get('项目编码', ''))
        name = str(row.get('项目名称', ''))
        category = str(row.get('分类', ''))

        if not code or code == 'nan':
            continue

        material_name = CATEGORY_TO_MATERIAL.get(category)

        if category not in category_stats:
            category_stats[category] = {'total': 0, 'mapped': 0, 'unmapped': 0}
        category_stats[category]['total'] += 1

        if not material_name:
            category_stats[category]['unmapped'] += 1
            continue

        mapping = ListMaterialMapping(
            list_item_code=code,
            list_item_name=name,
            list_version='2024',
            material_code='',
            material_name=material_name,
            match_type='category_mapped',
            similarity=80.0,
        )
        new_mappings.append(mapping)
        category_stats[category]['mapped'] += 1

    print(f"\n生成映射：{len(new_mappings)} 条（按F列分类映射）")

    # 清空旧映射，插入新映射
    db.query(ListMaterialMapping).delete()
    db.commit()
    print("已清空旧映射")

    db.bulk_save_objects(new_mappings)
    db.commit()
    print("已插入新映射")

    print('\n=== 分类统计 ===')
    for category, stats in sorted(category_stats.items(), key=lambda x: -x[1]['total']):
        if stats['mapped'] > 0:
            print(f'  {category}: {stats["mapped"]}/{stats["total"]} 已映射')

    print(f'\n总计：{sum(s["mapped"] for s in category_stats.values())}/{sum(s["total"] for s in category_stats.values())}')

finally:
    db.close()
