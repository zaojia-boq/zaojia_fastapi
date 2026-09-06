# -*- coding: utf-8 -*-
"""数据质量纯指标（M3 §3.2 / §7.1 落地）。

纯函数模块，**不依赖 odoo**，可被纯函数 pytest 直接 import（importlib loader 模式，
同 data.gb_code）。

compute_metrics(rows) 计算四个仪表盘指标（M3 §3.2 / §7.1）：
- coverage          : material_dict_id 非空的行占比
- match_key_quality : match_key_source ∈ {dict, std} 的行占比（优先级 1+2，§7.1）
- data_source_dist  : 按 data_source_type 的计数分布
- anomaly_rate      : anomaly_flag == 'error' 的行占比
- m3_pass / m4_pass : 达标门（M3 参考 / M4 迁移门槛，§7.1）

阈值（偏差）默认 30 —— 但纯模块无法读 env，故 default_deviation_threshold() 仅返回
整数 30；真正的读取（ir.config_parameter 'zaojia.price_deviation_threshold'）在
services.data_quality_service 层完成（§4.2：阈值存系统参数，非 boq_item 字段）。
"""
# 优先级 1+2 的聚合键来源（§7.1：dict > std 计为"高质量匹配"）
HIGH_QUALITY_SOURCES = frozenset(['dict', 'std'])

# 参考阈值（§7.1）
M3_COVERAGE_MIN = 0.70
M3_ANOMALY_MAX = 0.15
M4_COVERAGE_MIN = 0.80
M4_ANOMALY_MAX = 0.10

# 偏差阈值默认整数（百分比）
DEFAULT_DEVIATION_THRESHOLD = 30


def _safe_div(num, den):
    if not den:
        return 0.0
    return num / den


def _is_empty_material_dict_id(value):
    """material_dict_id 视为"空"的取值（B 类 M2O，id 为 int≥1）。"""
    return value in (False, None, 0, '')


def compute_metrics(rows):
    """计算数据质量指标。

    参数 rows: list[dict]，每行含键：
        material_dict_id  (int | False | None)  —— 物料字典关联（B 类）
        match_key_source  (str)                 —— dict/std/code/raw/...
        data_source_type  (str)                 —— completed/control_price/...
        anomaly_flag      (str)                 —— normal/warning/error/...

    返回 dict（见 M3 §3.2 / §7.1）：
        coverage, match_key_quality, data_source_dist,
        anomaly_rate, m3_pass, m4_pass
    """
    rows = rows or []
    total = len(rows)
    if total == 0:
        return {
            'coverage': 0.0,
            'match_key_quality': 0.0,
            'data_source_dist': {},
            'anomaly_rate': 0.0,
            'm3_pass': False,
            'm4_pass': False,
        }

    covered = 0
    high_quality = 0
    anomaly = 0
    dist = {}
    for r in rows:
        # coverage：material_dict_id 非空
        if not _is_empty_material_dict_id(r.get('material_dict_id')):
            covered += 1
        # match_key_quality（优先级 1+2，§7.1）
        if r.get('match_key_source') in HIGH_QUALITY_SOURCES:
            high_quality += 1
        # anomaly_rate（error 计入）
        if r.get('anomaly_flag') == 'error':
            anomaly += 1
        # data_source_dist 分布计数
        dst = r.get('data_source_type') or 'unknown'
        dist[dst] = dist.get(dst, 0) + 1

    coverage = _safe_div(covered, total)
    match_key_quality = _safe_div(high_quality, total)
    anomaly_rate = _safe_div(anomaly, total)

    return {
        'coverage': coverage,
        'match_key_quality': match_key_quality,
        'data_source_dist': dist,
        'anomaly_rate': anomaly_rate,
        'm3_pass': bool(coverage >= M3_COVERAGE_MIN and anomaly_rate < M3_ANOMALY_MAX),
        'm4_pass': bool(coverage >= M4_COVERAGE_MIN and anomaly_rate < M4_ANOMALY_MAX),
    }


def default_deviation_threshold():
    """偏差阈值默认整数（百分比），纯函数，不触碰 env。

    真正的读取在 services.data_quality_service 层经 ir.config_parameter 完成
    （get-or-create 默认 DEFAULT_DEVIATION_THRESHOLD）。
    """
    return DEFAULT_DEVIATION_THRESHOLD
