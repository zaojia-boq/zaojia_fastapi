# -*- coding: utf-8 -*-
"""M3.6 成本库评估门槛 Service（FastAPI/SQLAlchemy 版）。

职责（M3 §7 / §8）：评估当前数据质量是否达到 M4「成本库与语义检索」的启动门槛。
双门槛，缺一不可：
    覆盖率 ≥ 80%  且  异常率 < 10%

算法来源：原 Odoo 版 cost_catalog_gate 纯函数（算法规格 100% 继承）。
纯函数依赖：data/cost_catalog_gate.py（evaluate_gate / evaluate_gate_from_metrics），
从 Odoo 版原样复制零改动。

实现：调用 data_quality_service.get_dashboard() 获取质量指标，
再喂给 evaluate_gate_from_metrics() 判定门槛，返回结构化信封。

边界：本 Service 为读操作，不写任何数据；门槛未通过时返回 blockers 列表
（人类可读的未达标说明），供 UI 提示与 M4 启动决策。
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services import data_quality_service
from data.cost_catalog_gate import evaluate_gate_from_metrics

# 错误码前缀
ERROR_PREFIX = 'COST_CATALOG_'


def _err(trace_id, code, message):
    """错误信封。"""
    return {
        'success': False,
        'data': None,
        'total': 0,
        'warnings': [],
        'trace_id': trace_id,
        'message': message,
        'error': {'code': code, 'message': message},
    }


def get_gate_status(db: Session, active_only: bool = True) -> dict[str, Any]:
    """成本库启动门槛评估 → 结构化信封。

    流程：
    1. 调用 data_quality_service.get_dashboard() 获取四环指标；
    2. 喂给 evaluate_gate_from_metrics() 做双门槛判定；
    3. 返回质量指标 + 门槛判定结果 + blockers（未达标说明）。

    返回 data 内含：
    - metrics: {coverage, match_key_quality, data_source_dist, anomaly_rate, m3_pass, m4_pass, deviation_threshold}
    - gate: {passed, coverage_ok, anomaly_ok, coverage, anomaly_rate, thresholds, blockers}
    - recommendation: '可以启动 M4 成本库建设' / '暂不建议启动 M4，需先改善数据质量'
    """
    trace_id = uuid.uuid4().hex
    try:
        # 1. 获取质量指标
        quality = data_quality_service.get_dashboard(db, active_only=active_only)
        if not quality.get('success'):
            return _err(trace_id, f'{ERROR_PREFIX}QUALITY_FAILED',
                        f'质量指标获取失败: {quality.get("message", "unknown")}')

        metrics = quality['data']

        # 2. 双门槛判定
        gate = evaluate_gate_from_metrics(metrics)

        # 3. 建议
        if gate['passed']:
            recommendation = '数据质量达标，可以启动 M4 成本库与语义检索建设'
        else:
            recommendation = '数据质量未达标，暂不建议启动 M4；请先改善以下项：' + '；'.join(gate['blockers'])

        return {
            'success': True,
            'data': {
                'metrics': metrics,
                'gate': gate,
                'recommendation': recommendation,
            },
            'total': quality['total'],
            'warnings': quality.get('warnings', []),
            'trace_id': trace_id,
        }
    except Exception as exc:
        return _err(trace_id, f'{ERROR_PREFIX}GATE_FAILED', f'门槛评估失败: {exc}')
