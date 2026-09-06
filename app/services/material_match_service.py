# -*- coding: utf-8 -*-
"""M3.4 快速匹配 Service（FastAPI/SQLAlchemy 版）。

FROZEN 契约（M3 §5 / §9.2 / 架构 §19）：
- find_matches(db, boq_item_ids) → READ-ONLY，返回 Top-5 候选信封；
- confirm_match(db, payload)     → WRITE（B 类），仅填空字段、绝不覆盖已有 B 类值，
  写审计四元组（operator / reason / trace_id / timestamp，架构 §19.7）。

算法来源：原 Odoo 版 material_match_service.py（算法规格 100% 继承，框架切换）。
纯函数依赖：data/match_score.py（score_candidates / high_confidence），从 Odoo 版原样复制。

边界铁律：
- 仅候选建议，绝不自动改 boq_item；人工确认后回填 std_name/std_spec/material_dict_id（M3 §5.1）；
- B 类字段仅填空，绝不覆盖已有值（M3 §5.6 + M1 §4.9）；
- 回填后 match_key 由 before_update 事件监听器自动重算（M1.2）；
- 错误统一机器可识别错误码，前缀 MATCH_。
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from app.models.material_dict import MaterialDict
from app.core.audit import log_audit
from data.match_score import score_candidates, high_confidence


def _err(code, msg, trace_id):
    """错误信封（success=False / data=None / error_code+message）。"""
    return {
        'success': False,
        'data': None,
        'error_code': code,
        'message': msg,
        'total': 0,
        'warnings': [],
        'trace_id': trace_id,
    }


def _build_dict_rows(db: Session, dict_ids=None) -> list[dict]:
    """从 material_dict 构建候选行（L3 规格集合为主）。

    每个 dict_row 含：id / name / spec / category_path。
    spec 取 cat_l3（L3 规格集合名），无 cat_l3 时回退 name。
    category_path 用 cat_l1/cat_l2/cat_l3 拼接。
    """
    query = db.query(MaterialDict).filter(MaterialDict.level == 'l3')
    if dict_ids:
        query = db.query(MaterialDict).filter(MaterialDict.id.in_(list(dict_ids)))
    rows = []
    for d in query.all():
        cat_path = '/'.join(p for p in [d.cat_l1, d.cat_l2, d.cat_l3] if p)
        rows.append({
            'id': d.id,
            'name': d.name or '',
            'spec': d.cat_l3 or d.name or '',
            'category_path': cat_path or d.name or '',
        })
    return rows


# ---------------------------------------------------------------------------
# READ：find_matches（无写操作）
# ---------------------------------------------------------------------------

def find_matches(db: Session, boq_item_ids: list[int]) -> dict[str, Any]:
    """召回候选 → 结构化信封（§19.6）。

    boq_item 的匹配输入取真实字段：query_name=item_name，
    query_spec=item_feature（天然语言来源，M3 §5.3）。
    返回 {boq_item_id: [Top-5 候选...]}，每个候选含 dict_id/name/spec/score/category_path。
    """
    trace_id = uuid.uuid4().hex
    warnings = []

    if not boq_item_ids:
        return {
            'success': True,
            'data': {},
            'total': 0,
            'warnings': ['boq_item_ids 为空'],
            'trace_id': trace_id,
        }

    recs = db.query(BoqItem).filter(BoqItem.id.in_(boq_item_ids)).all()
    found_ids = {r.id for r in recs}
    for bid in boq_item_ids:
        if bid not in found_ids:
            warnings.append(f'boq_item {bid} 不存在')

    dict_rows = _build_dict_rows(db)
    data = {}
    for rec in recs:
        cands = score_candidates(
            rec.item_name or '',
            rec.item_feature or '',
            dict_rows,
        )
        data[rec.id] = cands[:5]

    return {
        'success': True,
        'data': data,
        'total': len(recs),
        'warnings': warnings,
        'trace_id': trace_id,
    }


# ---------------------------------------------------------------------------
# WRITE：confirm_match（B 类写，仅填空、绝不覆盖）
# ---------------------------------------------------------------------------

def confirm_match(db: Session, payload: dict) -> dict[str, Any]:
    """确认匹配回填 → 结构化信封（§19.6），写审计四元组（§19.7）。

    payload = {
      "operator": str, "reason": str, "trace_id": str(可选),
      "items": [{"boq_item_id":int, "dict_id":int, "fill_empty_only":bool(可选)}]
    }

    对每个 item：仅把 std_name/std_spec/material_dict_id 填到当前为空的字段，
    绝不覆盖已有 B 类值（M3 §5.6 + M1 §4.9）。
    fill_empty_only 且高置信（high_confidence）→ 视为自动链接，reason 打 auto_linked 标记。
    回填后 match_key 由 before_update 事件监听器自动重算（M1.2）。
    """
    if not isinstance(payload, dict):
        return _err('MATCH_INVALID_PAYLOAD', 'payload 必须是 dict', uuid.uuid4().hex)

    operator = payload.get('operator')
    reason = payload.get('reason')
    trace_id = payload.get('trace_id') or uuid.uuid4().hex
    items = payload.get('items')

    if not operator or not reason or not isinstance(items, list):
        return _err('MATCH_INVALID_PAYLOAD', '缺少 operator/reason/items', trace_id)

    filled = 0
    ignored = 0
    results = []
    warnings = []

    for item in items:
        boq_id = item.get('boq_item_id')
        dict_id = item.get('dict_id')
        fill_empty_only = bool(item.get('fill_empty_only', False))

        boq = db.query(BoqItem).filter(BoqItem.id == boq_id).first()
        if not boq:
            warnings.append(f'boq_item {boq_id} 不存在')
            results.append({'boq_item_id': boq_id, 'status': 'not_found'})
            continue

        d = db.query(MaterialDict).filter(MaterialDict.id == dict_id).first()
        if not d:
            warnings.append(f'material_dict {dict_id} 不存在')
            results.append({'boq_item_id': boq_id, 'status': 'dict_not_found'})
            continue

        # 是否自动链接：fill_empty_only 且高置信（Top-1 命中且 high_confidence）
        auto_link = False
        if fill_empty_only:
            cands = score_candidates(
                boq.item_name or '', boq.item_feature or '',
                _build_dict_rows(db),
            )
            auto_link = bool(cands) and cands[0]['dict_id'] == dict_id \
                and high_confidence(cands)

        # 仅填空，绝不覆盖已有 B 类值
        vals = {}
        filled_fields = []
        if not boq.std_name and (d.name or '').strip():
            vals['std_name'] = d.name
            filled_fields.append('std_name')
        if not boq.std_spec and (d.cat_l3 or d.name or '').strip():
            vals['std_spec'] = d.cat_l3 or d.name
            filled_fields.append('std_spec')
        if not boq.material_dict_id:
            vals['material_dict_id'] = d.id
            filled_fields.append('material_dict_id')

        if vals:
            audit_reason = reason
            if auto_link:
                audit_reason = '高置信自动链接 rapidfuzz=0.99 — ' + audit_reason

            # 逐字段写审计日志（B 类字段变更，append-only）
            for field_name in filled_fields:
                old_val = getattr(boq, field_name, None)
                new_val = vals[field_name]
                log_audit(
                    db=db,
                    model='boq_item',
                    res_id=boq.id,
                    action='write',
                    field_name=field_name,
                    old_value=str(old_val) if old_val is not None else None,
                    new_value=str(new_val) if new_val is not None else None,
                    operator=operator,
                    reason=audit_reason,
                    trace_id=trace_id,
                    batch_id=boq.import_batch_id,
                )

            # 执行回填（before_update 事件监听器自动重算 match_key）
            for k, v in vals.items():
                setattr(boq, k, v)
            db.flush()

            filled += 1
            results.append({
                'boq_item_id': boq_id,
                'dict_id': dict_id,
                'status': 'auto_linked' if auto_link else 'filled',
                'filled_fields': filled_fields,
            })
        else:
            ignored += 1
            results.append({
                'boq_item_id': boq_id,
                'dict_id': dict_id,
                'status': 'ignored',
                'filled_fields': [],
            })

    db.commit()
    return {
        'success': True,
        'data': {'filled': filled, 'ignored': ignored, 'items': results},
        'total': len(items),
        'warnings': warnings,
        'trace_id': trace_id,
    }
