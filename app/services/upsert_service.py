# -*- coding: utf-8 -*-
"""upsert_service —— 分层 Upsert 入库（M1.3 实现，SQLAlchemy 版）。

职责（M1 §4.9）：upsert_rows(db, batch_id, parsed_rows) —— 按 (import_batch_id,
sequence) 匹配、候选键兜底、A 类可覆盖、B 类禁删禁静默覆盖、孤儿行软标记
不自动删（孤儿 B 类回灌 v6.5）。返回四项计数信封 {created, updated,
orphaned, preserved_manual}。

一句话：**重导只能增加或修正「从 Excel 来的东西」，绝不能带走「人脑产出的
东西」**（A/B 分层定义写进 data/field_spec.py 常量，不是注释）。

设计来源：原 Odoo 版 services/upsert_service.py（算法 100% 继承，仅 ORM 切换）。
- A_FIELDS / B_FIELDS / B_DEFAULTS 单一事实源：data/field_spec.py
- 审计日志：app.core.audit.log_audit（落库）
"""
from collections import defaultdict
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from app.models.import_batch import ImportBatch
from app.core.audit import log_audit
from data.field_spec import A_FIELDS, B_FIELDS, B_DEFAULTS


def _norm(s: Optional[str]) -> str:
    """简单归一化（去空白、小写），供候选键比较用。"""
    return ' '.join((s or '').strip().lower().split())


def _make_candidate_key(item: BoqItem) -> Optional[tuple]:
    """生成候选键元组（None 表示无法构建）。"""
    code = (item.item_code or '').strip()
    name = _norm(item.item_name or '')
    unit = (item.unit_std or '').strip()
    if not (code or name or unit):
        return None
    return (code, name, unit)


def _build_candidate_index(items: List[BoqItem]) -> Dict[tuple, List[BoqItem]]:
    """构建 (item_code, item_name_norm, unit_std) → [item] 索引。"""
    idx = defaultdict(list)
    for item in items:
        key = _make_candidate_key(item)
        if key:
            idx[key].append(item)
    return idx


def _find_by_candidate(
    row: Dict[str, Any],
    idx: Dict[tuple, List[BoqItem]],
) -> Optional[BoqItem]:
    """按候选键在索引中查找；命中唯一者返回，命中多个返回 sequence 最接近的。"""
    code = (row.get('item_code') or '').strip()
    name = _norm(row.get('item_name') or '')
    unit = (row.get('unit_std') or '').strip()
    key = (code, name, unit)
    if key == ('', '', ''):
        return None
    candidates = idx.get(key, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # 多候选：取 sequence 与新行最接近的
    target_seq = row.get('sequence', 0) or 0
    closest = min(candidates, key=lambda r: abs((r.sequence or 0) - target_seq))
    return closest


def _update_existing(
    target: BoqItem,
    row: Dict[str, Any],
    audit_changes: List[tuple],
) -> None:
    """更新已有行：A 类覆盖，B 类保留（已有值不覆盖），收集 B 类变更。"""
    # A 类：可覆盖
    for f in A_FIELDS:
        v = row.get(f)
        if v is not None:
            setattr(target, f, v)

    # B 类：已有值保留，仅空时写入
    for f in B_FIELDS:
        v = row.get(f)
        existing = getattr(target, f, None)
        if existing:
            continue  # 已有 B 类值 → 禁静默覆盖
        if v is not None:
            old = getattr(target, f, None)
            if old != v:
                audit_changes.append((target, f, old, v))
            setattr(target, f, v)


def _create_new(
    db: Session,
    batch_id: int,
    row: Dict[str, Any],
) -> BoqItem:
    """新建行：A/B 类字段一起写入（新建行无历史 B 类值，可全量写入）。"""
    vals = {
        'import_batch_id': batch_id,
        'data_source_type': row.get('data_source_type') or B_DEFAULTS.get('data_source_type', 'completed'),
        'sequence': row.get('sequence', 0),
    }
    for f in A_FIELDS | B_FIELDS:
        v = row.get(f)
        if v is not None:
            vals[f] = v
    # B 类默认值兜底
    for f, default in B_DEFAULTS.items():
        if f not in vals:
            vals[f] = default
    item = BoqItem(**vals)
    db.add(item)
    db.flush()
    return item


def _backfill_orphan_b_fields(
    orphans: List[BoqItem],
    new_items: List[BoqItem],
    stats: Dict[str, int],
    audit_changes: List[tuple],
) -> None:
    """孤儿行 B 类回灌（v6.5 P0-3）。

    规则：孤儿行与新建行经 material_dict_id 命中，判定为同一物料，
    则把孤儿行的 B 类字段回灌到新建行（新建行为空时才写）。
    回灌后 stats['preserved_manual'] += 1（每条孤儿行仅算一次）。

    参数
    ----
    new_items : List[BoqItem] —— 本次 upsert 新建的行（不包含原行/已更新行）
    """
    # 按 material_dict_id 分组匹配
    dict_to_orphan = defaultdict(list)
    dict_to_new = defaultdict(list)
    for rec in orphans:
        did = rec.material_dict_id
        if did:
            dict_to_orphan[did].append(rec)
    for rec in new_items:
        did = rec.material_dict_id
        if did:
            dict_to_new[did].append(rec)

    for did, orphs in dict_to_orphan.items():
        new_rows = dict_to_new.get(did, [])
        if not new_rows:
            continue
        for orph in orphs:
            # 回灌到 sequence 最接近的新建行
            target = min(
                new_rows,
                key=lambda r: abs((r.sequence or 0) - (orph.sequence or 0)),
            )
            # 把孤儿的 B 类字段写入新建行（新建行为空时才写）
            for f in B_FIELDS:
                v = getattr(orph, f, None)
                if v and not getattr(target, f, None):
                    old = getattr(target, f, None)
                    setattr(target, f, v)
                    audit_changes.append((target, f, old, v))
                    stats['preserved_manual'] += 1
            break  # 每个孤儿只回灌一次


def _write_audit(
    db: Session,
    batch_id: int,
    operator: Optional[str],
    audit_changes: List[tuple],
) -> None:
    """批量写审计日志：B 类变更逐条记录。"""
    grouped = defaultdict(list)
    for item, field, old, new in audit_changes:
        grouped[(item.id, field)].append((old, new))

    for (item_id, field), pairs in grouped.items():
        log_audit(
            db=db,
            model="boq_item",
            res_id=item_id,
            action="write",
            field_name=field,
            old_value=str(pairs[0][0]) if pairs[0][0] is not None else "",
            new_value=str(pairs[-1][1]) if pairs[-1][1] is not None else "",
            operator=operator or "system",
            reason="导入分层 Upsert 回灌 B 类标注",
            batch_id=batch_id,
        )


def upsert_rows(
    db: Session,
    batch_id: int,
    parsed_rows: List[Dict[str, Any]],
    operator: Optional[str] = None,
) -> Dict[str, int]:
    """批量入库 → {created, updated, orphaned, preserved_manual}。

    参数
    ----
    db : Session —— 数据库会话
    batch_id : int —— 导入批次 ID
    parsed_rows : list[dict] —— 解析后的行数据（含 sequence/item_code/item_name 等）
    operator : str, optional —— 操作人（审计用）

    返回
    ----
    dict —— {created, updated, orphaned, preserved_manual}

    算法（M1 §4.9）：
    1. 按 (batch, sequence) 优先匹配已有行；
    2. 未命中则按候选键 (item_code, item_name_norm, unit_std) 兜底；
    3. 命中 → A 类覆盖更新，B 类保留（已有值不覆盖）；
    4. 未命中 → 新建行；
    5. 孤儿行（原批次有、新导入无）→ active=False + orphaned=True，不物理删除；
    6. 孤儿 B 类回灌：同 material_dict_id 的孤儿 B 类标注回灌到新建行。
    """
    # 1. 建立「序列号 → 新行」映射
    new_seq_set = {r.get('sequence') for r in parsed_rows if r.get('sequence')}

    # 2. 查询本批次现存活跃行（active=True），按 sequence 建索引
    existing = db.query(BoqItem).filter(
        BoqItem.import_batch_id == batch_id,
        BoqItem.active.is_(True),
    ).order_by(BoqItem.sequence).all()

    original_seq_to_existing = {r.sequence: r for r in existing if r.sequence is not None}
    seq_to_existing = dict(original_seq_to_existing)

    # 3. 候选键兜底索引
    candidate_idx = _build_candidate_index(existing)

    # 4. 计数
    stats = {'created': 0, 'updated': 0, 'orphaned': 0, 'preserved_manual': 0}

    # 5. B 类变更审计记录收集
    audit_changes = []  # [(item, field, old, new)]

    # 5.1 新建行列表（回灌专用：只回灌到新建行，不包含原行/已更新行）
    newly_created = []

    # ------------------------------------------------------------------
    # 主循环：逐新行匹配
    # ------------------------------------------------------------------
    for row in parsed_rows:
        seq = row.get('sequence')
        if not seq:
            continue  # 无行序跳过

        target = None

        # 优先按 (batch, seq) 匹配
        if seq in seq_to_existing:
            target = seq_to_existing[seq]

        # 未命中则按候选键兜底
        if target is None:
            target = _find_by_candidate(row, candidate_idx)

        if target:
            # 命中已有行 → A 类更新，B 类保留
            stats['updated'] += 1
            _update_existing(target, row, audit_changes)
        else:
            # 未命中 → 新建行
            stats['created'] += 1
            target = _create_new(db, batch_id, row)
            newly_created.append(target)
            # 同步到 seq_to_existing 供后续匹配
            seq_to_existing[seq] = target
            # 增量更新候选键索引
            key = _make_candidate_key(target)
            if key:
                candidate_idx[key].append(target)

    # 6. 孤儿行检测：原批次有、新导入无的活跃行
    orphans = []
    for seq, rec in original_seq_to_existing.items():
        if seq not in new_seq_set:
            orphans.append(rec)
            stats['orphaned'] += 1

    # 7. 孤儿行 B 类回灌（v6.5 P0-3）：只回灌到新建行
    if orphans and newly_created:
        _backfill_orphan_b_fields(orphans, newly_created, stats, audit_changes)

    # 8. 孤儿行软标记（不物理删除）
    for rec in orphans:
        rec.active = False
        rec.orphaned = True

    # 9. 审计日志：B 类变更逐条记录
    if audit_changes:
        _write_audit(db, batch_id, operator, audit_changes)

    db.flush()
    return stats


def preview_upsert(
    db: Session,
    batch_id: Optional[int],
    parsed_rows: List[Dict[str, Any]],
) -> Dict[str, int]:
    """预览模式：只计算不写库 → 同结构信封。

    用于导入向导预览页展示「新增 N / 更新 M / 孤儿 K」。
    batch_id 为 None 时按全新批次预计算（existing 为空 → 全部 created）。
    """
    new_seq_set = {r.get('sequence') for r in parsed_rows if r.get('sequence')}

    query = db.query(BoqItem).filter(BoqItem.active.is_(True))
    if batch_id is not None:
        query = query.filter(BoqItem.import_batch_id == batch_id)
    existing = query.all()

    seq_to_existing = {r.sequence: r for r in existing if r.sequence is not None}
    candidate_idx = _build_candidate_index(existing)

    stats = {'created': 0, 'updated': 0, 'orphaned': 0, 'preserved_manual': 0}

    for row in parsed_rows:
        seq = row.get('sequence')
        if not seq:
            continue
        target = seq_to_existing.get(seq)
        if not target:
            target = _find_by_candidate(row, candidate_idx)
        if target:
            stats['updated'] += 1
        else:
            stats['created'] += 1

    orphaned_seqs = set(seq_to_existing.keys()) - new_seq_set
    stats['orphaned'] = len(orphaned_seqs)
    # 预览不计 preserved_manual（需真实写入才能判定）
    return stats
