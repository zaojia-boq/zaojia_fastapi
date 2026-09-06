# -*- coding: utf-8 -*-
"""query_service —— 清单查询/检索服务（M2-查询导出 实现）。

职责（M1 §16.2 / 架构 §19.3）：search / get / export —— 供查询 API 共用。
统计口径纪律：默认 domain 必须含 active=True（写在 Service，不写在路由）。

设计来源：原 Odoo 版 services/boq_query_service.py（算法 100% 继承，框架切换）。
"""
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem


def source_location(item: BoqItem) -> Dict[str, Any]:
    """组装单元格级溯源定位 → envelope{archive_path, sheet, row, note, batch_biz_id}。

    设计来源：原 Odoo 版 evidence_service.source_location()。
    """
    batch = item.import_batch if hasattr(item, 'import_batch') else None
    sheet = item.source_sheet or ''
    row = item.sequence
    return {
        'archive_path': getattr(batch, 'archive_path', None) if batch else None,
        'sheet': sheet,
        'row': row,
        'note': f'{sheet} 第 {row} 行' if sheet and row else None,
        'batch_biz_id': getattr(batch, 'biz_id', None) if batch else None,
    }


def search_items(
    db: Session,
    domain: Optional[List[Any]] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """分页查询 → envelope{data, total, warnings, trace_id, query_domain}。

    domain：list[tuple]，如 [('item_name', 'like', '%土方%')]。
    默认含 ('active', '=', True)（统计口径纪律，M1 §4.7）。
    """
    domain = domain or []

    # 构建过滤条件（白名单字段，防止任意 SQL 注入）
    query = db.query(BoqItem)
    filters = _build_filters(domain)
    if filters:
        query = query.filter(*filters)
    # 默认只查有效行（统计口径纪律）
    query = query.filter(BoqItem.active.is_(True))

    total = query.count()
    recs = (
        query.order_by(BoqItem.import_batch_id.desc(), BoqItem.sequence.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    data = []
    for it in recs:
        data.append({
            'biz_id': it.biz_id,
            'id': it.id,
            'item_code': it.item_code,
            'item_name': it.item_name,
            'unit_std': it.unit_std,
            'quantity_num': float(it.quantity_num) if it.quantity_num is not None else None,
            'unit_rate_num': float(it.unit_rate_num) if it.unit_rate_num is not None else None,
            'total_num': float(it.total_num) if it.total_num is not None else None,
            'data_source_type': it.data_source_type,
            'anomaly_flag': it.anomaly_flag,
            'source_location': source_location(it),
        })

    return {
        'data': data,
        'total': total,
        'warnings': [],
        'trace_id': uuid.uuid4().hex,
        'query_domain': domain,
    }


def get_item(db: Session, biz_id: str) -> Optional[Dict[str, Any]]:
    """按稳定业务 ID 取单条（None 表示未找到）。"""
    it = db.query(BoqItem).filter(BoqItem.biz_id == biz_id).first()
    if not it:
        return None
    return {
        'biz_id': it.biz_id,
        'id': it.id,
        'item_code': it.item_code,
        'item_code_raw': it.item_code_raw,
        'item_name': it.item_name,
        'item_feature': it.item_feature,
        'unit': it.unit,
        'unit_std': it.unit_std,
        'quantity': it.quantity,
        'unit_rate': it.unit_rate,
        'total': it.total,
        'quantity_num': float(it.quantity_num) if it.quantity_num is not None else None,
        'unit_rate_num': float(it.unit_rate_num) if it.unit_rate_num is not None else None,
        'total_num': float(it.total_num) if it.total_num is not None else None,
        'std_name': it.std_name,
        'std_spec': it.std_spec,
        'material_dict_id': it.material_dict_id,
        'data_source_type': it.data_source_type,
        'province': it.province,
        'price_period': it.price_period.isoformat() if it.price_period else None,
        'anomaly_flag': it.anomaly_flag,
        'anomaly_reason': it.anomaly_reason,
        'source_location': source_location(it),
        'active': it.active,
        'orphaned': it.orphaned,
    }


def export_items(
    db: Session,
    domain: Optional[List[Any]] = None,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """导出筛选结果集（全字段，供 Excel/CSV 序列化）。

    不含 internal 字段（checksum_* 等）。
    """
    domain = domain or []

    query = db.query(BoqItem)
    filters = _build_filters(domain)
    if filters:
        query = query.filter(*filters)
    query = query.filter(BoqItem.active.is_(True))

    recs = (
        query.order_by(BoqItem.import_batch_id.desc(), BoqItem.sequence.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            'biz_id': it.biz_id,
            'item_code': it.item_code,
            'item_code_raw': it.item_code_raw,
            'item_name': it.item_name,
            'item_feature': it.item_feature,
            'unit': it.unit,
            'unit_std': it.unit_std,
            'quantity': it.quantity,
            'unit_rate': it.unit_rate,
            'total': it.total,
            'quantity_num': float(it.quantity_num) if it.quantity_num is not None else None,
            'unit_rate_num': float(it.unit_rate_num) if it.unit_rate_num is not None else None,
            'total_num': float(it.total_num) if it.total_num is not None else None,
            'std_name': it.std_name,
            'std_spec': it.std_spec,
            'material_dict_id': it.material_dict_id,
            'data_source_type': it.data_source_type,
            'province': it.province,
            'price_period': it.price_period.isoformat() if it.price_period else None,
            'anomaly_flag': it.anomaly_flag,
            'source_sheet': it.source_sheet,
            'source_path': it.source_path,
            'active': it.active,
            'orphaned': it.orphaned,
        }
        for it in recs
    ]


# ------------------------------------------------------------------
# 内部辅助
# ------------------------------------------------------------------

# 查询白名单字段（字段名 → BoqItem 属性）
_QUERYABLE_FIELDS = {
    'item_name': BoqItem.item_name,
    'item_code': BoqItem.item_code,
    'unit_std': BoqItem.unit_std,
    'data_source_type': BoqItem.data_source_type,
    'anomaly_flag': BoqItem.anomaly_flag,
    'province': BoqItem.province,
    'import_batch_id': BoqItem.import_batch_id,
    'project_name': BoqItem.project_name,
    'std_name': BoqItem.std_name,
}


def _build_filters(domain: List[Any]) -> List[Any]:
    """把 domain（Odoo 风格 tuple 列表）转为 SQLAlchemy 过滤条件。

    支持操作符：=, !=, like, ilike, in, not in, >, >=, <, <=。
    仅允许白名单字段（防止任意字段注入）。
    """
    filters = []
    for cond in domain:
        # 兼容 ('field', '=', value) 和 ('field', value) 两种写法
        if len(cond) == 3:
            field, op, value = cond
        elif len(cond) == 2:
            field, value = cond
            op = '='
        else:
            continue

        if field not in _QUERYABLE_FIELDS:
            continue
        attr = _QUERYABLE_FIELDS[field]

        if op == '=':
            filters.append(attr == value)
        elif op == '!=':
            filters.append(attr != value)
        elif op == 'like':
            filters.append(attr.like(f'%{value}%'))
        elif op == 'ilike':
            filters.append(attr.ilike(f'%{value}%'))
        elif op == 'in':
            filters.append(attr.in_(value))
        elif op == 'not in':
            filters.append(attr.not_in(value))
        elif op == '>':
            filters.append(attr > value)
        elif op == '>=':
            filters.append(attr >= value)
        elif op == '<':
            filters.append(attr < value)
        elif op == '<=':
            filters.append(attr <= value)
    return filters
