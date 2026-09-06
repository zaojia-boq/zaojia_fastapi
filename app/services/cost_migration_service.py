# -*- coding: utf-8 -*-
"""M4.2 成本库迁移服务 —— boq_item → cost_catalog 聚合迁移。

设计来源：M4模块设计.md §4 迁移策略。

核心规则（§4.2）：
1. 聚合域：active=True + data_source_type='completed' + unit_rate_num 非空
2. 按 match_key 分组，每组计算 avg/min/max/sample_count
3. 取最新一条（按 price_period 降序）的标准化字段 + 溯源
4. upsert：同一 match_key 只保留一条；更新时**覆盖数值字段**（avg/min/max/latest），
   **保留人工标注**（std_name/std_spec/material_dict_id 如果已有则不覆盖）
5. 迁移后原 boq_item 不被修改或删除（boq_item 仍是数据源）

门槛闸门（§4.1）：迁移前检查 M3.6 评估结果（覆盖率≥80% & 异常率<10%），
不达标时拒绝迁移并返回 blockers。

安全：
- B 类字段（std_name/std_spec/material_dict_id）迁移时只从 boq_item 取最新值，
  已有 cost_catalog 记录的 B 类字段不被覆盖（§4.2 去重规则）
- 所有迁移操作写 audit_log（action='cost_migration'）
"""
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from app.models.cost_catalog import CostCatalog
from app.models.import_batch import ImportBatch
from app.core.audit import log_audit
from app.services.cost_catalog_service import get_gate_status

logger = logging.getLogger(__name__)


def _aggregate_for_match_key(db: Session, match_key: str) -> dict | None:
    """对单个 match_key 聚合统计。返回 None 表示无 completed 数据。"""
    items = db.query(BoqItem).filter(
        BoqItem.active == True,  # noqa: E712
        BoqItem.match_key == match_key,
        BoqItem.data_source_type == 'completed',
        BoqItem.unit_rate_num != None,  # noqa: E711
    ).all()

    if not items:
        return None

    rates = [float(r.unit_rate_num) for r in items if r.unit_rate_num is not None]
    if not rates:
        return None

    # 取最新一条（按 price_period 降序，空值排最后）
    sorted_items = sorted(
        items,
        key=lambda x: (x.price_period or date.min),
        reverse=True,
    )
    latest = sorted_items[0]

    return {
        'match_key': match_key,
        'match_key_source': latest.match_key_source or 'code',
        'std_name': latest.std_name or latest.item_name or '',
        'std_spec': latest.std_spec or latest.item_feature or '',
        'material_dict_id': latest.material_dict_id,
        'unit_std': latest.unit or '',
        'avg_rate': sum(rates) / len(rates),
        'min_rate': min(rates),
        'max_rate': max(rates),
        'sample_count': len(rates),
        'latest_price': float(latest.unit_rate_num),
        'latest_period': latest.price_period,
        'latest_source': latest.project_name or (latest.import_batch.name if latest.import_batch else None),
    }


def preview_migration(db: Session, match_key_prefix: str = "") -> dict:
    """迁移预览（不写库）。返回将迁移的 match_key 列表及统计摘要。

    Args:
        match_key_prefix: 可选，只迁移指定前缀的 match_key（如 "dict:"）。
                          空字符串表示全部。
    """
    # 取所有有 completed 数据的 distinct match_key
    q = db.query(BoqItem.match_key).filter(
        BoqItem.active == True,  # noqa: E712
        BoqItem.data_source_type == 'completed',
        BoqItem.unit_rate_num != None,  # noqa: E711
        BoqItem.match_key != None,  # noqa: E711
    ).distinct()

    if match_key_prefix:
        q = q.filter(BoqItem.match_key.like(f"{match_key_prefix}%"))

    match_keys = [r[0] for r in q.all()]

    preview_items = []
    low_sample = 0
    for mk in match_keys:
        agg = _aggregate_for_match_key(db, mk)
        if agg is None:
            continue
        if agg['sample_count'] < 3:
            low_sample += 1
        preview_items.append({
            'match_key': mk,
            'std_name': agg['std_name'],
            'sample_count': agg['sample_count'],
            'avg_rate': round(agg['avg_rate'], 4),
            'min_rate': agg['min_rate'],
            'max_rate': agg['max_rate'],
            'low_sample_warning': agg['sample_count'] < 3,
        })

    return {
        'total_match_keys': len(match_keys),
        'will_migrate': len(preview_items),
        'low_sample_count': low_sample,
        'items': preview_items,
    }


def execute_migration(
    db: Session,
    operator: str,
    reason: str,
    match_key_prefix: str = "",
    skip_gate_check: bool = False,
) -> dict:
    """执行迁移：boq_item → cost_catalog upsert。

    Args:
        operator: 操作人（写审计用）
        reason: 迁移原因（必填，写审计用）
        match_key_prefix: 可选前缀过滤
        skip_gate_check: 跳过门槛检查（仅 admin 可用于强制迁移，默认 False）

    Returns:
        迁移结果摘要（created/updated/skipped 计数 + 明细）
    """
    # 1. 门槛闸门
    if not skip_gate_check:
        gate = get_gate_status(db)
        if not gate['success'] or not gate['data']['gate']['passed']:
            blockers = gate['data']['gate'].get('blockers', [])
            return {
                'success': False,
                'error': 'gate_not_passed',
                'message': '成本库评估门槛未通过，拒绝迁移',
                'blockers': blockers,
                'recommendation': gate['data'].get('recommendation', ''),
            }

    # 2. 取所有有 completed 数据的 distinct match_key
    q = db.query(BoqItem.match_key).filter(
        BoqItem.active == True,  # noqa: E712
        BoqItem.data_source_type == 'completed',
        BoqItem.unit_rate_num != None,  # noqa: E711
        BoqItem.match_key != None,  # noqa: E711
    ).distinct()

    if match_key_prefix:
        q = q.filter(BoqItem.match_key.like(f"{match_key_prefix}%"))

    match_keys = [r[0] for r in q.all()]

    created = 0
    updated = 0
    skipped = 0
    details = []

    for mk in match_keys:
        agg = _aggregate_for_match_key(db, mk)
        if agg is None:
            skipped += 1
            continue

        # upsert：按 match_key 查找已有记录
        existing = db.query(CostCatalog).filter(
            CostCatalog.match_key == mk,
            CostCatalog.active == True,  # noqa: E712
        ).first()

        if existing:
            # 更新：覆盖数值字段，保留 B 类人工标注
            existing.avg_rate = agg['avg_rate']
            existing.min_rate = agg['min_rate']
            existing.max_rate = agg['max_rate']
            existing.sample_count = agg['sample_count']
            existing.latest_price = agg['latest_price']
            existing.latest_period = agg['latest_period']
            existing.latest_source = agg['latest_source']
            existing.unit_std = agg['unit_std'] or existing.unit_std
            # B 类字段：仅当已有记录为空时才填充（不覆盖人工标注）
            if not existing.std_name:
                existing.std_name = agg['std_name']
            if not existing.std_spec:
                existing.std_spec = agg['std_spec']
            if existing.material_dict_id is None:
                existing.material_dict_id = agg['material_dict_id']
            if not existing.match_key_source:
                existing.match_key_source = agg['match_key_source']
            updated += 1
            details.append({'match_key': mk, 'action': 'updated'})
        else:
            # 新建
            record = CostCatalog(
                match_key=mk,
                match_key_source=agg['match_key_source'],
                std_name=agg['std_name'],
                std_spec=agg['std_spec'],
                material_dict_id=agg['material_dict_id'],
                unit_std=agg['unit_std'],
                avg_rate=agg['avg_rate'],
                min_rate=agg['min_rate'],
                max_rate=agg['max_rate'],
                sample_count=agg['sample_count'],
                latest_price=agg['latest_price'],
                latest_period=agg['latest_period'],
                latest_source=agg['latest_source'],
                active=True,
            )
            db.add(record)
            created += 1
            details.append({'match_key': mk, 'action': 'created'})

    db.flush()

    # 3. 写审计日志
    log_audit(
        db=db,
        model='cost_catalog',
        res_id=None,
        action='cost_migration',
        operator=operator,
        reason=reason,
        trace_id=f"migration_{len(match_keys)}keys_{created}c_{updated}u",
        field_name='batch_migration',
        new_value=f"新建{created}/更新{updated}/跳过{skipped}",
    )
    db.commit()

    return {
        'success': True,
        'total_match_keys': len(match_keys),
        'created': created,
        'updated': updated,
        'skipped': skipped,
        'details': details,
    }


def list_cost_catalog(
    db: Session,
    page: int = 1,
    per_page: int = 50,
    keyword: str = "",
) -> dict:
    """成本库列表查询（只读）。"""
    q = db.query(CostCatalog).filter(CostCatalog.active == True)  # noqa: E712

    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(
            CostCatalog.std_name.like(like),
            CostCatalog.std_spec.like(like),
            CostCatalog.match_key.like(like),
        ))

    total = q.count()
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    items = q.order_by(CostCatalog.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        'total': total,
        'page': page,
        'pages': pages,
        'per_page': per_page,
        'items': [{
            'id': r.id,
            'match_key': r.match_key,
            'match_key_source': r.match_key_source,
            'std_name': r.std_name,
            'std_spec': r.std_spec,
            'unit_std': r.unit_std,
            'avg_rate': float(r.avg_rate) if r.avg_rate else None,
            'min_rate': float(r.min_rate) if r.min_rate else None,
            'max_rate': float(r.max_rate) if r.max_rate else None,
            'sample_count': r.sample_count,
            'latest_price': float(r.latest_price) if r.latest_price else None,
            'latest_period': r.latest_period.isoformat() if r.latest_period else None,
            'latest_source': r.latest_source,
        } for r in items],
    }
