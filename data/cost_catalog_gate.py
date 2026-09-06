# -*- coding: utf-8 -*-
"""M3.6 成本库启动门槛判定（M3 §8 / M4 启动判据落地）。

纯函数模块，**不依赖 odoo**，可被 pure_tests/ 直接 import（importlib loader 模式，
同 data.quality_metrics / data.gb_code）。

作用（M3 §8）：M4「成本库与语义检索」的启动判据 —— 数据质量须先达标，否则
建库就是垃圾进垃圾出（GIGO）。判定采用**双门槛，缺一不可**：

    覆盖率 ≥ 80%  且  异常率 < 10%

阈值常量与 data.quality_metrics 的 **M4 门槛一致**（M3 §7.1）：
- M4_COVERAGE_MIN = 0.80
- M4_ANOMALY_MAX  = 0.10

⚠️ 为什么不直接 import quality_metrics：data/ 目录的硬性惯例是「三文件互不交叉
import，保证各自可独立被纯函数测试按文件加载」（见 data/__init__.py）。故此处
**本地定义常量**，由 pure_tests/test_cost_catalog_gate.py 中的
test_thresholds_consistent_with_quality_metrics 断言两处不漂移。跨文件 import 会
破坏按文件加载（相对导入在无包上下文时抛 ImportError）。

边界语义（与 quality_metrics.compute_metrics 的 m4_pass 保持完全一致）：
- 覆盖率用 **≥**（达到即可）；
- 异常率用 **<**（等于 10% 视为未达标，卡在门槛上不算通过）。
"""
# M4 门槛（与 quality_metrics.M4_* 同源，由纯测试守卫不漂移）
M4_COVERAGE_MIN = 0.80
M4_ANOMALY_MAX = 0.10

# 门槛键名（供 UI / 日志展示）
GATE_KEYS = ('coverage', 'anomaly_rate')


def _pct(value):
    """比率转百分比（保留 1 位小数），用于人类可读输出。"""
    return round(float(value) * 100, 1)


def evaluate_gate(coverage, anomaly_rate, min_coverage=None, max_anomaly=None):
    """双门槛判定（纯函数）。

    参数：
        coverage       覆盖率比率（0~1）
        anomaly_rate   异常率比率（0~1）
        min_coverage   覆盖率下限，默认 M4_COVERAGE_MIN(0.80)
        max_anomaly    异常率上限（严格小于），默认 M4_ANOMALY_MAX(0.10)

    返回 dict（结构化，供架构 §19.6 信封的 data 承载）：
        passed             : bool  —— 双门槛是否均通过
        coverage_ok        : bool
        anomaly_ok         : bool
        coverage           : float —— 原样回填，便于调用方直接渲染
        anomaly_rate       : float
        thresholds         : {min_coverage, max_anomaly}
        blockers           : list[str] —— 未达标项的人类可读说明（供 UI 提示）
    """
    min_cov = M4_COVERAGE_MIN if min_coverage is None else min_coverage
    max_ano = M4_ANOMALY_MAX if max_anomaly is None else max_anomaly

    coverage = float(coverage or 0.0)
    anomaly_rate = float(anomaly_rate or 0.0)

    coverage_ok = coverage >= min_cov
    anomaly_ok = anomaly_rate < max_ano

    blockers = []
    if not coverage_ok:
        blockers.append(
            '覆盖率 %.1f%% 未达 %.1f%%（缺 %.1f 个百分点）'
            % (_pct(coverage), _pct(min_cov), _pct(min_cov - coverage)))
    if not anomaly_ok:
        blockers.append(
            '异常率 %.1f%% 未低于 %.1f%%' % (_pct(anomaly_rate), _pct(max_ano)))

    return {
        'passed': bool(coverage_ok and anomaly_ok),
        'coverage_ok': coverage_ok,
        'anomaly_ok': anomaly_ok,
        'coverage': coverage,
        'anomaly_rate': anomaly_rate,
        'thresholds': {'min_coverage': min_cov, 'max_anomaly': max_ano},
        'blockers': blockers,
    }


def evaluate_gate_from_metrics(metrics):
    """从 quality_metrics.compute_metrics() 的返回值直接判定（常用入口）。

    metrics 需含 'coverage' 与 'anomaly_rate' 两键；缺失时按 0 处理，
    由 evaluate_gate 的门槛判定自然判为未达标（空库不得放行）。
    """
    metrics = metrics or {}
    return evaluate_gate(metrics.get('coverage', 0.0),
                         metrics.get('anomaly_rate', 0.0))
