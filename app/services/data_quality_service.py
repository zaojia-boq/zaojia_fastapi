# -*- coding: utf-8 -*-
"""M3.2 数据质量仪表盘 Service（FastAPI/SQLAlchemy 版）。

职责（M3 §3.2 / §7.1）：读取 boq_item 行，计算四个进度环指标，返回结构化信封。
- coverage          : material_dict_id 非空的行占比
- match_key_quality : match_key_source ∈ {dict, std} 的行占比（高质量匹配）
- data_source_dist  : 按 data_source_type 的计数分布
- anomaly_rate      : anomaly_flag == 'error' 的行占比
- m3_pass / m4_pass : 达标门（M3 参考 / M4 迁移门槛）

算法来源：原 Odoo 版 data_quality_service.py（算法规格 100% 继承，框架切换）。
纯函数依赖：data/quality_metrics.py（compute_metrics / default_deviation_threshold），
从 Odoo 版原样复制零改动。

偏差阈值：Odoo 版存 ir.config_parameter，FastAPI 版暂用默认值 30（后续可扩展为
config.Settings 字段或数据库配置表）。

边界：本 Service 为读操作，不写 boq_item、不触发 B 类写审计。
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from data.quality_metrics import compute_metrics, default_deviation_threshold

# 错误码前缀
ERROR_PREFIX = 'QUALITY_'


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


def get_dashboard(db: Session, active_only: bool = True) -> dict[str, Any]:
    """数据质量仪表盘 → 结构化信封。

    读取 boq_item 行 → compute_metrics 纯函数 → 四环指标 + 达标门 + 偏差阈值。

    参数：
    - active_only: 默认只统计 active=True 的行（统计口径纪律）。

    返回 data 内含：
    - coverage / match_key_quality / data_source_dist / anomaly_rate
    - m3_pass (coverage>=0.70 & anomaly<0.15) / m4_pass (coverage>=0.80 & anomaly<0.10)
    - deviation_threshold (默认 30)
    """
    trace_id = uuid.uuid4().hex
    try:
        query = db.query(BoqItem)
        if active_only:
            query = query.filter(BoqItem.active == True)
        recs = query.all()
        total = len(recs)

        # 规整逐行：material_dict_id 为空时用 False（与 Odoo 版 M2O 语义一致）
        rows = [{
            'material_dict_id': r.material_dict_id if r.material_dict_id else False,
            'match_key_source': r.match_key_source or '',
            'data_source_type': r.data_source_type or '',
            'anomaly_flag': r.anomaly_flag or '',
        } for r in recs]

        metrics = compute_metrics(rows)
        payload = dict(metrics)
        payload['deviation_threshold'] = default_deviation_threshold()

        return {
            'success': True,
            'data': payload,
            'total': total,
            'warnings': [],
            'trace_id': trace_id,
        }
    except Exception as exc:
        return _err(trace_id, f'{ERROR_PREFIX}COMPUTE_FAILED', f'质量指标计算失败: {exc}')
