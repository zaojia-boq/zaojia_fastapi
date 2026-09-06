# -*- coding: utf-8 -*-
"""M3.1 单价分析 Service（FastAPI/SQLAlchemy 版）。

职责（M3模块设计.md §3.2 / §3.3 / §3.4）：
- get_kpis(db, domain)      默认域 = completed 行（含 unit_rate_num），返回 KPI 信封；
- get_analysis(db, domain)  按 aggregate_id / match_key_source / province / price_period
                            四维度分组聚合，返回带异常标记的分析信封。

算法来源：原 Odoo 版 price_service.py（算法规格 100% 继承，框架切换）。
纯函数依赖：data/price_calc.py（compute_kpis / analyze_group / is_anomaly / deviation_pct），
从 Odoo 版原样复制，零框架依赖。

边界铁律：
- 默认 completed 域只在此定义一次，绝不重复（M3 §3.2 ⚠️）；
- 异常判定只读展示，不写回 boq_item.anomaly_flag（M3 §3.4）；
- 错误统一机器可识别错误码，前缀 PRICE_。
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from data.price_calc import compute_kpis, analyze_group

# 默认域：已完工程口径，排除 pending_review / control_price / bid_price / info_price，
# 且必须有数值单价（M3 §3.2 ⚠️「不在此重复定义」——全模块唯一出处）。
DEFAULT_COMPLETED_DOMAIN = [
    ('data_source_type', '=', 'completed'),
    ('unit_rate_num', '!=', None),
]

# get_analysis 的四维度（与 M3 §3.3 透视表分组维度一致）
_ANALYSIS_DIMS = (
    'aggregate_id',
    'match_key_source',
    'province',
    'price_period',
)


# ---------------------------------------------------------------------------
# domain → SQLAlchemy filter 转换器（轻量，支持 = / != / like / in）
# ---------------------------------------------------------------------------

def _apply_domain(query, domain):
    """将 Odoo 风格 domain 列表转为 SQLAlchemy filter 条件。

    支持的 leaf 格式：('field', '=', value) / ('field', '!=', value) /
    ('field', 'like', '%value%') / ('field', 'in', [v1, v2])。
    不支持逻辑操作符 & / | / !（M3 场景不需要，需要时再扩展）。
    """
    if not domain:
        return query
    for leaf in domain:
        if not isinstance(leaf, (list, tuple)) or len(leaf) < 3:
            continue
        field_name, op, value = leaf[0], leaf[1], leaf[2]
        if not hasattr(BoqItem, field_name):
            continue
        col = getattr(BoqItem, field_name)
        if op == '=':
            query = query.filter(col == value)
        elif op == '!=':
            query = query.filter(col != value)
        elif op == 'like':
            query = query.filter(col.like(value))
        elif op == 'in':
            query = query.filter(col.in_(value))
    return query


def _resolve_domain(domain):
    """domain 为空/None → 使用默认 completed 域（唯一出处，禁止重复定义）。"""
    if not domain:
        return list(DEFAULT_COMPLETED_DOMAIN)
    return domain


def _err(trace_id, code, message):
    """错误信封（success=False / data=None / message+error.code）。"""
    return {
        'success': False,
        'data': None,
        'total': 0,
        'warnings': [],
        'trace_id': trace_id,
        'message': message,
        'error': {'code': code, 'message': message},
    }


# ---------------------------------------------------------------------------
# Service 函数
# ---------------------------------------------------------------------------

def get_kpis(db: Session, domain=None) -> dict[str, Any]:
    """KPI 卡片数据 → 信封{data: compute_kpis 结果}。

    默认域 = completed + unit_rate_num 非空（唯一出处）。
    返回：sample_count / avg / min / max / anomaly_count（相对本批 avg 判定）。
    """
    trace_id = uuid.uuid4().hex
    try:
        domain = _resolve_domain(domain)
        query = db.query(BoqItem).filter(BoqItem.active == True)
        query = _apply_domain(query, domain)
        recs = query.all()

        # 喂纯函数 compute_kpis（逐行 unit_rate_num）
        rows = [{'unit_rate_num': float(r.unit_rate_num) if r.unit_rate_num is not None else None}
                for r in recs]
        kpis = compute_kpis(rows)

        return {
            'success': True,
            'data': kpis,
            'total': kpis['sample_count'],
            'warnings': [],
            'trace_id': trace_id,
        }
    except Exception as exc:
        return _err(trace_id, 'PRICE_KPIS_FAILED', f'KPI 计算失败: {exc}')


def get_analysis(db: Session, domain=None, threshold: float = 0.30) -> dict[str, Any]:
    """四维度分组分析 → 信封{data:{维度: analyze_group 结果}}。

    维度：aggregate_id / match_key_source / province / price_period（M3 §3.3）。
    每组返回：group / avg / min / max / count / anomaly_count（相对该组自身 avg）。
    threshold 参数保留为前向兼容（当前 analyze_group 用默认 0.30）。
    """
    trace_id = uuid.uuid4().hex
    try:
        domain = _resolve_domain(domain)
        query = db.query(BoqItem).filter(BoqItem.active == True)
        query = _apply_domain(query, domain)
        recs = query.all()

        # 规整逐行：price_period(date) 转 str，保证信封 JSON 可序列化
        rows = []
        for r in recs:
            rows.append({
                'unit_rate_num': float(r.unit_rate_num) if r.unit_rate_num is not None else None,
                'aggregate_id': r.aggregate_id,
                'match_key_source': r.match_key_source,
                'province': r.province,
                'price_period': r.price_period.isoformat() if r.price_period else None,
            })

        data = {dim: analyze_group(rows, dim, measures=None)
                for dim in _ANALYSIS_DIMS}

        return {
            'success': True,
            'data': data,
            'total': len(recs),
            'warnings': [],
            'trace_id': trace_id,
        }
    except Exception as exc:
        return _err(trace_id, 'PRICE_ANALYSIS_FAILED', f'分析失败: {exc}')
