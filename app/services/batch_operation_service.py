# -*- coding: utf-8 -*-
"""M3.5 批量操作 Service（FastAPI/SQLAlchemy 版）。

职责（M3 §6.1 / §6.2）：
- confirm_anomalies(db, payload) ：批量修改 anomaly_flag（B 类字段），强制填 reason，逐字段写审计；
- switch_data_source(db, payload)：批量修改 data_source_type（B 类字段），切换到 completed 强制二次确认，逐字段写审计。

算法来源：原 Odoo 版批量操作逻辑（M3 §6 设计稿，算法规格继承）。
核心模式与 M3.4 confirm_match 一致：B 类字段变更 → 强制 reason → 逐字段 log_audit → db.commit。

边界铁律：
- anomaly_flag / data_source_type 均为 B 类字段（M1 §4.9），无 reason 拒绝写入；
- 批量操作 > 50 行需二次确认（payload.require_confirm=True）；
- 切换到 completed 时防污染闸门：警告"此操作会影响历史均价统计"；
- 审计 append-only，逐字段记录 old_value/new_value。
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from app.core.audit import log_audit

# 批量操作行数上限（超过需二次确认）
BATCH_CONFIRM_THRESHOLD = 50

# anomaly_flag 合法值
VALID_ANOMALY_FLAGS = ('normal', 'warning', 'error')

# data_source_type 合法值
VALID_DATA_SOURCE_TYPES = ('completed', 'pending_review', 'control_price', 'bid_price', 'info_price')


def _err(code, msg, trace_id):
    """错误信封。"""
    return {
        'success': False,
        'data': None,
        'error_code': code,
        'message': msg,
        'total': 0,
        'warnings': [],
        'trace_id': trace_id,
    }


def _validate_payload(payload, trace_id):
    """校验批量操作 payload 的通用字段。"""
    if not isinstance(payload, dict):
        return _err('BATCH_INVALID_PAYLOAD', 'payload 必须是 dict', trace_id)
    operator = payload.get('operator')
    reason = payload.get('reason')
    item_ids = payload.get('item_ids')
    if not operator or not reason or not isinstance(item_ids, list) or not item_ids:
        return _err('BATCH_INVALID_PAYLOAD', '缺少 operator/reason/item_ids', trace_id)
    return None


# ---------------------------------------------------------------------------
# 异常行批量确认（M3 §6.1）
# ---------------------------------------------------------------------------

def confirm_anomalies(db: Session, payload: dict) -> dict[str, Any]:
    """批量修改 anomaly_flag（B 类字段，强制 reason，逐字段写审计）。

    payload = {
      "operator": str, "reason": str, "trace_id": str(可选),
      "item_ids": [int, ...],
      "target_flag": "normal" | "warning",  # 目标状态（不允许直接设为 error）
      "require_confirm": bool(可选，>50行时必须为 True)
    }

    铁律：
    - anomaly_flag 是 B 类字段，无 reason 拒绝；
    - 目标状态不允许 'error'（error 由算法/导入标记，人工只能确认为 normal/warning）；
    - > 50 行需 require_confirm=True；
    - 逐字段写 audit_log（old_value/new_value 完整）。
    """
    trace_id = payload.get('trace_id') or uuid.uuid4().hex
    bad = _validate_payload(payload, trace_id)
    if bad:
        return bad

    target_flag = payload.get('target_flag')
    if target_flag not in ('normal', 'warning'):
        return _err('BATCH_INVALID_TARGET', 'target_flag 必须是 normal 或 warning', trace_id)

    item_ids = payload['item_ids']
    if len(item_ids) > BATCH_CONFIRM_THRESHOLD and not payload.get('require_confirm'):
        return _err('BATCH_CONFIRM_REQUIRED',
                    f'批量操作 {len(item_ids)} 行超过 {BATCH_CONFIRM_THRESHOLD}，需 require_confirm=True 二次确认',
                    trace_id)

    items = db.query(BoqItem).filter(BoqItem.id.in_(item_ids)).all()
    found_ids = {i.id for i in items}
    not_found = [i for i in item_ids if i not in found_ids]

    updated = 0
    skipped = 0
    results = []

    for item in items:
        old_flag = item.anomaly_flag
        if old_flag == target_flag:
            skipped += 1
            results.append({'id': item.id, 'status': 'skipped', 'reason': '已是目标状态'})
            continue

        # 逐字段写审计（B 类字段变更）
        log_audit(
            db=db, model='boq_item', res_id=item.id, action='write',
            field_name='anomaly_flag',
            old_value=str(old_flag) if old_flag else None,
            new_value=target_flag,
            operator=payload['operator'], reason=payload['reason'],
            trace_id=trace_id, batch_id=item.import_batch_id,
        )

        item.anomaly_flag = target_flag
        updated += 1
        results.append({'id': item.id, 'status': 'updated',
                        'old_value': old_flag, 'new_value': target_flag})

    db.commit()

    warnings = []
    if not_found:
        warnings.append(f'{len(not_found)} 条记录不存在')

    return {
        'success': True,
        'data': {'updated': updated, 'skipped': skipped, 'not_found': not_found, 'items': results},
        'total': len(item_ids),
        'warnings': warnings,
        'trace_id': trace_id,
    }


# ---------------------------------------------------------------------------
# 数据性质批量切换（M3 §6.2）
# ---------------------------------------------------------------------------

def switch_data_source(db: Session, payload: dict) -> dict[str, Any]:
    """批量修改 data_source_type（B 类字段，强制 reason，逐字段写审计）。

    payload = {
      "operator": str, "reason": str, "trace_id": str(可选),
      "item_ids": [int, ...],
      "target_type": "completed" | "pending_review" | "control_price" | "bid_price" | "info_price",
      "require_confirm": bool(可选，>50行或切换到completed时必须为 True)
    }

    铁律：
    - data_source_type 是 B 类字段，无 reason 拒绝；
    - 切换到 completed 时防污染闸门：需 require_confirm=True（影响历史均价统计）；
    - > 50 行需 require_confirm=True；
    - 逐字段写 audit_log（old_value/new_value 完整）。
    """
    trace_id = payload.get('trace_id') or uuid.uuid4().hex
    bad = _validate_payload(payload, trace_id)
    if bad:
        return bad

    target_type = payload.get('target_type')
    if target_type not in VALID_DATA_SOURCE_TYPES:
        return _err('BATCH_INVALID_TARGET',
                    f'target_type 必须是 {VALID_DATA_SOURCE_TYPES} 之一', trace_id)

    item_ids = payload['item_ids']

    # 防污染闸门：切换到 completed 需二次确认
    if target_type == 'completed' and not payload.get('require_confirm'):
        return _err('BATCH_COMPLETED_CONFIRM_REQUIRED',
                    '切换到 completed 会影响历史均价统计，需 require_confirm=True 二次确认',
                    trace_id)

    if len(item_ids) > BATCH_CONFIRM_THRESHOLD and not payload.get('require_confirm'):
        return _err('BATCH_CONFIRM_REQUIRED',
                    f'批量操作 {len(item_ids)} 行超过 {BATCH_CONFIRM_THRESHOLD}，需 require_confirm=True',
                    trace_id)

    items = db.query(BoqItem).filter(BoqItem.id.in_(item_ids)).all()
    found_ids = {i.id for i in items}
    not_found = [i for i in item_ids if i not in found_ids]

    updated = 0
    skipped = 0
    to_completed = 0
    results = []

    for item in items:
        old_type = item.data_source_type
        if old_type == target_type:
            skipped += 1
            results.append({'id': item.id, 'status': 'skipped', 'reason': '已是目标性质'})
            continue

        # 统计切换到 completed 的行数（用于警告）
        if target_type == 'completed' and old_type != 'completed':
            to_completed += 1

        # 逐字段写审计（B 类字段变更）
        log_audit(
            db=db, model='boq_item', res_id=item.id, action='write',
            field_name='data_source_type',
            old_value=str(old_type) if old_type else None,
            new_value=target_type,
            operator=payload['operator'], reason=payload['reason'],
            trace_id=trace_id, batch_id=item.import_batch_id,
        )

        item.data_source_type = target_type
        updated += 1
        results.append({'id': item.id, 'status': 'updated',
                        'old_value': old_type, 'new_value': target_type})

    db.commit()

    warnings = []
    if not_found:
        warnings.append(f'{len(not_found)} 条记录不存在')
    if to_completed > 0:
        warnings.append(f'{to_completed} 条记录切换到 completed，将计入历史均价统计（防污染闸门已确认）')

    return {
        'success': True,
        'data': {'updated': updated, 'skipped': skipped, 'not_found': not_found,
                 'to_completed': to_completed, 'items': results},
        'total': len(item_ids),
        'warnings': warnings,
        'trace_id': trace_id,
    }
