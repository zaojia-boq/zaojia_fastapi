# -*- coding: utf-8 -*-
"""批次生命周期 API（M2-批次管理 实现）。

路由：
- POST /api/import/batches/{batch_id}/soft-delete —— 软删除（批次+清单项进回收站）
- POST /api/import/batches/{batch_id}/restore —— 还原（批次+清单项恢复，孤儿行一并恢复）
- POST /api/import/batches/{batch_id}/hard-delete —— 硬删除（三板斧闸门：管理员+确认名+CSV快照+30天宽限+B类闸门）

设计来源：原 Odoo 版 import_batch.action_soft_delete/action_restore + batch_hard_delete_wizard
（算法 100% 继承，框架切换）。

硬删除闸门（M2 §5.2/§5.3）：
1. 仅管理员（admin 角色）
2. 二次确认：输入批次名（confirm_name 必须与批次名一致）
3. 回收站宽限期：软删后 30 天内禁止硬删（可配置，设 0 表示不限制）
4. CSV 快照：硬删除前自动导出全量清单项快照（含软删/孤儿行，active_test=False 语义）
5. B 类闸门：含 B 类人工标注（std_name/std_spec/material_dict_id 非空）时强制导出快照
6. 审计：硬删除落 audit_log（含快照路径）
"""
import csv
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user, require_role, ROLE_ADMIN
from app.core.audit import log_audit, ACTION_SOFT_DELETE, ACTION_RESTORE, ACTION_HARD_DELETE
from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.services import archive_service

logger = logging.getLogger("zaojia.batch")

router = APIRouter(prefix="/api/import", tags=["批次管理"])

# 回收站宽限期默认值（天）。设 0 = 不限制（随时可硬删）。
DEFAULT_GRACE_DAYS = 30

# 快照列（与 Odoo 版一致）
SNAPSHOT_COLUMNS = [
    'sequence', 'item_code', 'item_code_raw', 'item_name', 'item_feature',
    'unit', 'unit_std', 'quantity', 'unit_rate', 'total', 'std_name',
    'std_spec', 'data_source_type', 'anomaly_flag', 'source_sheet',
    'active', 'orphaned',
]


@router.post("/batches/{batch_id}/soft-delete")
async def soft_delete_batch(
    batch_id: int,
    reason: str = Body(..., embed=True),
    user=Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """软删除批次：批次 + 关联清单项一并标记 active=False（进回收站）。

    M2 §5.2：软删除后进入回收站，deleted_at 作为 30 天硬删窗口起点。
    """
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if not batch.active:
        raise HTTPException(status_code=400, detail="批次已在回收站中")

    # 批次 + 关联清单项一并软删
    items = db.query(BoqItem).filter(BoqItem.import_batch_id == batch.id).all()
    for item in items:
        item.active = False
        item.orphaned = False  # 软删时清孤儿标记（还原时统一恢复）
    batch.active = False
    batch.deleted_at = datetime.now(timezone.utc)

    log_audit(
        db=db,
        model="import_batch",
        res_id=batch.id,
        action=ACTION_SOFT_DELETE,
        operator=user.get('username', 'system'),
        reason=reason or f"软删除批次 {batch.name}",
        batch_id=batch.id,
    )
    db.commit()

    return {
        'ok': True,
        'batch_id': batch.id,
        'deleted_at': batch.deleted_at.isoformat(),
        'items_soft_deleted': len(items),
    }


@router.post("/batches/{batch_id}/restore")
async def restore_batch(
    batch_id: int,
    user=Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """还原批次：批次 + 关联清单项恢复 active=True（孤儿行一并恢复）。

    NOTE：必须显式查全量清单项（含孤儿/软删行），不能只查 active=True 的。
    """
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    if batch.active:
        raise HTTPException(status_code=400, detail="批次不在回收站中")

    # 显式查全量关联项（含孤儿/软删行）
    items = db.query(BoqItem).filter(BoqItem.import_batch_id == batch.id).all()
    for item in items:
        item.active = True
        item.orphaned = False
    batch.active = True
    batch.deleted_at = None

    log_audit(
        db=db,
        model="import_batch",
        res_id=batch.id,
        action=ACTION_RESTORE,
        operator=user.get('username', 'system'),
        reason=f"还原批次 {batch.name}",
        batch_id=batch.id,
    )
    db.commit()

    return {
        'ok': True,
        'batch_id': batch.id,
        'items_restored': len(items),
    }


@router.post("/batches/{batch_id}/hard-delete")
async def hard_delete_batch(
    batch_id: int,
    confirm_name: str = Body(..., embed=True),
    user=Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """硬删除批次（三板斧闸门）：管理员 + 确认名 + CSV 快照 + 30 天宽限 + B 类闸门。

    流程：
    1. 权限校验（require_role(ROLE_ADMIN) 已做）；
    2. 名称确认：confirm_name 必须与批次名一致；
    3. 回收站宽限期：软删后 30 天内禁止硬删（deleted_at 为空则不限制）；
    4. CSV 快照导出（含软删/孤儿行全量）；
    5. B 类闸门：含人工标注强制导出快照（快照导出失败则拒绝）；
    6. 物理删除：先删清单项（外键 RESTRICT），再删批次；
    7. 审计：hard_delete 落 audit_log（含快照路径）。
    """
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    # 名称确认（二次确认）
    if confirm_name != batch.name:
        raise HTTPException(status_code=400, detail=f"输入的批次名与「{batch.name}」不一致，已取消")

    # 回收站宽限期闸门（M2 §5.2）
    grace_days = _get_grace_days()
    if grace_days and batch.deleted_at:
        deadline = batch.deleted_at + timedelta(days=grace_days)
        now = datetime.now(timezone.utc)
        # SQLite 读取 DateTime(timezone=True) 仍为 naive，统一补 UTC 时区后比较
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now < deadline:
            remaining = (deadline - now).days
            raise HTTPException(
                status_code=400,
                detail=f"批次「{batch.name}」仍在回收站宽限期内（剩余 {remaining} 天），暂不可硬删除",
            )

    # 全量清单项（含软删/孤儿行）
    items = db.query(BoqItem).filter(BoqItem.import_batch_id == batch.id).all()

    # B 类闸门：含人工标注则强制导出快照
    annotated = [it for it in items if it.std_name or it.std_spec or it.material_dict_id]

    # CSV 快照导出
    snapshot_path = _export_snapshot(batch, items)
    if snapshot_path is None:
        raise HTTPException(
            status_code=500,
            detail=f"快照导出失败：批次「{batch.name}」含 {len(annotated)} 条人工标注，"
                   "必须成功导出快照才能硬删除（人工资产闸门 §5.3）",
        )
    if annotated:
        logger.info('硬删除批次 %s：含 %d 条人工标注，已导出快照 %s',
                    batch.name, len(annotated), snapshot_path)

    # 物理删除：先删明细（外键 RESTRICT），再删批次
    batch_biz_id = batch.biz_id
    batch_name = batch.name
    for item in items:
        db.delete(item)
    db.delete(batch)
    db.flush()

    log_audit(
        db=db,
        model="import_batch",
        res_id=0,
        action=ACTION_HARD_DELETE,
        operator=user.get('username', 'system'),
        reason=f"硬删除批次 {batch_name}（biz_id={batch_biz_id}），CSV 快照：{snapshot_path}",
        batch_id=None,
    )
    db.commit()

    return {
        'ok': True,
        'batch_name': batch_name,
        'biz_id': batch_biz_id,
        'items_hard_deleted': len(items),
        'snapshot_path': snapshot_path,
        'annotated_count': len(annotated),
    }


# ------------------------------------------------------------------
# 内部辅助
# ------------------------------------------------------------------

def _get_grace_days() -> int:
    """回收站保留天数（M2 §5.2，可配置，默认 30）。

    读取环境变量 ZAOJIA_HARD_DELETE_GRACE_DAYS；缺失或非法值时回退 30。
    设 0 表示不限制宽限期（随时可硬删）。
    """
    raw = os.environ.get('ZAOJIA_HARD_DELETE_GRACE_DAYS', '')
    if raw is None or raw == '':
        return DEFAULT_GRACE_DAYS
    try:
        grace = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_GRACE_DAYS
    return grace if grace >= 0 else DEFAULT_GRACE_DAYS


def _export_snapshot(batch: ImportBatch, items: list) -> str | None:
    """导出批次全量清单项 CSV 到归档目录（人工资产闸门 §5.3）。

    items 为全量（含软删/孤儿行）。导出成功返回路径，失败返回 None。
    """
    try:
        root = archive_service.get_archive_root()
    except Exception:
        root = None

    if batch.archive_path:
        base = batch.archive_path + '.snapshot.csv'
    elif root is not None:
        snap_dir = root / 'snapshots'
        snap_dir.mkdir(parents=True, exist_ok=True)
        base = snap_dir / (f"{batch.biz_id or 'batch'}.csv")
    else:
        base = None

    if base is None:
        logger.warning('硬删除快照导出跳过：归档根目录未配置')
        return None

    path = str(base)
    try:
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=SNAPSHOT_COLUMNS)
            writer.writeheader()
            for it in items:
                writer.writerow({
                    'sequence': it.sequence,
                    'item_code': it.item_code or '',
                    'item_code_raw': it.item_code_raw or '',
                    'item_name': it.item_name or '',
                    'item_feature': it.item_feature or '',
                    'unit': it.unit or '',
                    'unit_std': it.unit_std or '',
                    'quantity': it.quantity or '',
                    'unit_rate': it.unit_rate or '',
                    'total': it.total or '',
                    'std_name': it.std_name or '',
                    'std_spec': it.std_spec or '',
                    'data_source_type': it.data_source_type or '',
                    'anomaly_flag': it.anomaly_flag or '',
                    'source_sheet': it.source_sheet or '',
                    'active': it.active,
                    'orphaned': it.orphaned,
                })
    except OSError as e:
        logger.error('硬删除快照导出失败：%s', e)
        return None
    return path
