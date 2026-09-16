"""一次性全量版本识别脚本：对所有 boq_item 跑 4 层筛选 + 两次校验，批量写回"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.db import SessionLocal
from app.models.boq_item import BoqItem
from data.version_lookup import classify_version_full
from sqlalchemy import text

s = SessionLocal()

# 1. 全量跑识别
print("=== 开始全量版本识别 ===")
items = s.query(BoqItem).filter(BoqItem.item_code.isnot(None)).all()
print(f"总条数: {len(items)}")

# 统计
stats = {"2013": 0, "2024": 0, "unknown": 0}
conf_stats = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
layer_stats = {1: 0, 2: 0, 3: 0, 4: 0}
updated = 0

for item in items:
    result = classify_version_full(item.item_code, item.item_name or "")
    new_version = result["version"]
    new_confidence = result["confidence"]

    # 只更新变化的
    if item.item_code_version != new_version:
        item.item_code_version = new_version
        updated += 1
    if item.version_confidence != new_confidence:
        item.version_confidence = new_confidence
        updated += 1

    # 加 version_confidence 字段（如果不存在先加列）
    stats[new_version] = stats.get(new_version, 0) + 1
    conf_stats[new_confidence] = conf_stats.get(new_confidence, 0) + 1
    layer_stats[result["layer"]] = layer_stats.get(result["layer"], 0) + 1

s.commit()

print(f"\n=== 识别结果 ===")
print(f"更新条数: {updated}")
print(f"\n版本分布:")
for v, c in sorted(stats.items()):
    print(f"  {v}: {c} 条 ({c/len(items)*100:.1f}%)")
print(f"\n置信度分布:")
for c, n in sorted(conf_stats.items()):
    print(f"  {c}: {n} 条 ({n/len(items)*100:.1f}%)")
print(f"\n命中层分布:")
for l, n in sorted(layer_stats.items()):
    print(f"  第{l}层: {n} 条 ({n/len(items)*100:.1f}%)")

# 2. 抽样验证
print(f"\n=== 抽样 10 条 ===")
sample_codes = ["030408001002", "030409001001", "031001001001", "010515001001", "010506001001"]
for code in sample_codes:
    result = classify_version_full(code, "")
    print(f"  {code} → {result}")

s.close()
print("\n=== 完成 ===")
