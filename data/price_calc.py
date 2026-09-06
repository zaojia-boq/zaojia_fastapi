# -*- coding: utf-8 -*-
"""M3 单价分析纯函数（L0，odoo-free）。

纯函数模块：**不依赖 odoo**，仅用标准库（math），可被纯函数 pytest 直接 import
（加载模式同 data/gb_code.py，经 importlib 按文件加载，避免触发 zaojia_boq 包）。

契约来源：
- M3模块设计.md §3.2 / §3.4 偏离判定规则、§9.1 纯函数验收判据；
- 误差码前缀 PRICE_ 由 Service 层封装（架构 §19.6），本层不返回信封。

函数：
- deviation_pct(current, historical_avg)            → float（百分比）
- is_anomaly(current, historical_avg, ...)           → bool
- compute_kpis(rows)                                → dict
- analyze_group(rows, group_key, measures=None)     → list[dict]
"""
import math

# 默认偏离阈值 / 样本下限（与 M3 §3.4 一致，阈值 30%、样本下限 3）
DEFAULT_THRESHOLD = 0.30
DEFAULT_MIN_SAMPLE = 3

# analyze_group 支持的合法分组维度（M3 §3.3 透视表分组维度）
GROUP_KEYS = ('aggregate_id', 'match_key_source', 'province', 'price_period')


def deviation_pct(current, historical_avg):
    """当前价相对历史均值的偏离百分比。

    (current - historical_avg) / historical_avg * 100；
    historical_avg == 0 时返回 0.0（避免除零，M3 §3.4 隐含约定）。
    """
    if historical_avg == 0:
        return 0.0
    return (current - historical_avg) / historical_avg * 100


def is_anomaly(current, historical_avg, threshold=DEFAULT_THRESHOLD,
               sample_count=0, min_sample=DEFAULT_MIN_SAMPLE):
    """判断当前价是否异常（M3 §3.4 偏离判定规则）。

    异常 iff  abs(deviation_pct) > threshold * 100  AND  sample_count >= min_sample。
    样本数不足下限时不判异常（统计不可靠，R3）。
    """
    if abs(deviation_pct(current, historical_avg)) > threshold * 100 \
            and sample_count >= min_sample:
        return True
    return False


def compute_kpis(rows):
    """逐行计算 KPI（M3 §3.2 卡片）。

    rows: list[dict]，每行的 'unit_rate_num' 为 float 或 None。
    过滤 None 后计算：样本数 / 均价 / 最低 / 最高 / 异常数。
    anomaly_count = 相对「本批计算的 avg」被标记为异常的值个数
                    （阈值 0.30、样本下限 3，与 §3.4 一致）。
    """
    vals = [r['unit_rate_num'] for r in rows
            if r.get('unit_rate_num') is not None]
    sample_count = len(vals)
    if sample_count == 0:
        return {
            'sample_count': 0,
            'avg': 0.0,
            'min': 0.0,
            'max': 0.0,
            'anomaly_count': 0,
        }
    avg = sum(vals) / sample_count
    anomaly_count = sum(
        1 for v in vals
        if is_anomaly(v, avg, DEFAULT_THRESHOLD, sample_count, DEFAULT_MIN_SAMPLE)
    )
    return {
        'sample_count': sample_count,
        'avg': avg,
        'min': min(vals),
        'max': max(vals),
        'anomaly_count': anomaly_count,
    }


def analyze_group(rows, group_key, measures=None):
    """按 group_key 维度分组聚合（M3 §3.3 透视表分组）。

    group_key ∈ {'aggregate_id','match_key_source','province','price_period'}。
    每组返回 {group, avg, min, max, count, anomaly_count}：
    - avg/min/max/count 基于该组 unit_rate_num（忽略 None）；
    - anomaly_count 相对该组自身 avg 判定（阈值 0.30、样本下限 3）。

    measures 参数保留为前向兼容（未来支持 quantity_num sum 等），当前未使用。
    """
    if group_key not in GROUP_KEYS:
        raise ValueError('非法分组维度: %r，应为 %s 之一' % (group_key, GROUP_KEYS))

    buckets = {}
    for r in rows:
        key = r.get(group_key)
        buckets.setdefault(key, []).append(r.get('unit_rate_num'))

    result = []
    for group_val, raw_vals in buckets.items():
        vals = [v for v in raw_vals if v is not None]
        count = len(vals)
        if count == 0:
            result.append({
                'group': group_val, 'avg': 0.0, 'min': 0.0,
                'max': 0.0, 'count': 0, 'anomaly_count': 0,
            })
            continue
        avg = sum(vals) / count
        anomaly_count = sum(
            1 for v in vals
            if is_anomaly(v, avg, DEFAULT_THRESHOLD, count, DEFAULT_MIN_SAMPLE)
        )
        result.append({
            'group': group_val,
            'avg': avg,
            'min': min(vals),
            'max': max(vals),
            'count': count,
            'anomaly_count': anomaly_count,
        })
    return result
