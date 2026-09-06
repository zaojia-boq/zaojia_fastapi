# -*- coding: utf-8 -*-
"""导入向导 API（M2.3 实现）。

路由：
- POST /api/import/upload —— 上传 Excel，解析，返回预览信封（不写库）
- POST /api/import/execute —— 执行导入（创建批次 + 归档 + upsert + 校验和）
- GET  /api/import/batches —— 批次列表
- GET  /api/import/batches/{batch_id} —— 批次详情
- GET  /api/import/batches/{batch_id}/items —— 批次明细行

权限：admin 可上传/执行；estimator/viewer 仅可查询。
"""
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user, require_role, ROLE_ADMIN
from app.core.audit import log_audit
from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.services.import_service import parse_excel, preview_parsed
from app.services.upsert_service import upsert_rows, preview_upsert
from app.services import archive_service

router = APIRouter(prefix="/api/import", tags=["导入"])
logger = logging.getLogger("zaojia.import")


def _validate_tmp_path(tmp_path: str, file_token: str) -> str | None:
    """校验 /execute 传入的 tmp_path（防路径穿越，2026-09-06 审查修复）。

    tmp_path 由客户端完全控制，若不校验将被 open()/归档/删除三处使用，
    可造成任意文件读取、归档外泄、原文件被删。校验规则（全满足才放行）：
      1. 绝对路径必须位于系统临时目录内（commonpath 判定，防 ../
         与符号链接逃逸）；
      2. 文件名必须等于 f"{file_token}.xlsx"（file_token 含分隔符时
         basename 自然不匹配，一并拒绝）；
      3. file_token 必须符合 /upload 生成的命名格式。

    返回规范化后的绝对路径；不合法返回 None。
    """
    if not tmp_path or not file_token:
        return None
    # file_token 格式：zaojia_import_<hash16>_<timestamp>
    if not re.fullmatch(r"zaojia_import_[0-9a-f]{1,32}_\d+", file_token):
        return None
    try:
        tmp_root = os.path.abspath(tempfile.gettempdir())
        target = os.path.abspath(tmp_path)
        if os.path.commonpath([target, tmp_root]) != tmp_root:
            return None
        expected = os.path.join(tmp_root, f"{file_token}.xlsx")
        if os.path.abspath(expected) != target:
            return None
    except (ValueError, OSError):
        return None
    return target


def _parse_or_400(file_bytes: bytes, filename: str, sheet: Optional[str] = None):
    """解析 Excel；任何解析失败统一转 400（不泄漏堆栈）。

    openpyxl 对非 Excel 文件抛 BadZipFile（不继承 ValueError），
    原实现只捕获 ValueError → 未捕获异常直达 500，并在 debug 下泄漏堆栈。
    """
    try:
        return parse_excel(file_bytes=file_bytes, filename=filename, sheet=sheet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 —— 上传内容为不可信输入，统一降级为 400
        logger.warning("Excel 解析失败（%s）: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail="文件解析失败：不是有效的 Excel 文件（.xlsx/.xlsm）")


@router.post("/upload")
async def upload_and_parse(
    file: UploadFile = File(...),
    sheet: Optional[str] = Form(None),
    user=Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """上传 Excel 并解析，返回预览信封（不写库）。

    流程：读取上传文件 → parse_excel 解析 → preview_parsed 精简信封。
    解析结果暂存到临时文件，供后续 /execute 使用（通过 file_token 关联）。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件")

    # 读取文件内容
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")

    # 解析（非 Excel 文件统一 400，不再 500）
    parsed = _parse_or_400(file_bytes, file.filename, sheet)

    # 暂存到临时文件（供 /execute 使用）
    tmp_dir = tempfile.gettempdir()
    file_token = f"zaojia_import_{parsed['file_hash'][:16]}_{int(datetime.now(timezone.utc).timestamp())}"
    tmp_path = os.path.join(tmp_dir, f"{file_token}.xlsx")
    with open(tmp_path, 'wb') as f:
        f.write(file_bytes)

    # 预览信封
    preview = preview_parsed(parsed)
    preview['file_token'] = file_token
    preview['file_hash'] = parsed['file_hash']
    preview['filename'] = parsed['filename']
    preview['sheet_name'] = parsed['sheet_name']
    preview['tmp_path'] = tmp_path

    return preview


@router.post("/execute")
async def execute_import(
    file_token: str = Form(...),
    tmp_path: str = Form(...),
    data_source_type: str = Form("completed"),
    province: Optional[str] = Form(None),
    price_period: Optional[str] = Form(None),
    user=Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """执行导入：创建批次 + 归档 + upsert + 校验和固化。

    流程：
    1. 读取临时文件 → parse_excel 重新解析（确保数据一致）
    2. 创建 ImportBatch（含 file_hash/row_count 等）
    3. 归档源文件（archive_service.archive）
    4. upsert_rows 入库（A 类覆盖/B 类保留/孤儿回灌）
    5. 固化校验和（checksum_count/checksum_total/checksum_hash）
    6. 写审计日志
    """
    # 路径穿越闸门（2026-09-06 审查修复）：必须位于临时目录且文件名匹配 file_token
    safe_path = _validate_tmp_path(tmp_path, file_token)
    if safe_path is None or not os.path.isfile(safe_path):
        raise HTTPException(status_code=400, detail="临时文件不存在或路径非法，请重新上传")

    with open(safe_path, 'rb') as f:
        file_bytes = f.read()

    # 重新解析
    parsed = _parse_or_400(file_bytes, os.path.basename(safe_path))

    # 1. 创建批次
    batch_name = f"{parsed.get('filename', '未命名')}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    batch = ImportBatch(
        name=batch_name,
        source_file=parsed.get('filename'),
        file_hash=parsed['file_hash'],
        row_count=parsed['row_count'] + parsed['skipped_count'],
        imported_count=0,  # upsert 后更新
        skipped_count=parsed['skipped_count'],
        anomaly_count=parsed['anomaly_count'],
        province=province,
        data_source_type=data_source_type,
        operator=user.get('username', 'system'),
    )
    db.add(batch)
    db.flush()

    # 2. 归档源文件
    archive_result = archive_service.archive(
        source_path=safe_path,
        file_hash=parsed['file_hash'],
        archiver=user.get('username', 'system'),
    )
    if archive_result['ok']:
        batch.archive_path = archive_result['archive_path']
    else:
        batch.archive_path = None
        # 归档失败不阻断导入，但记录异常
        batch.anomaly_count = (batch.anomaly_count or 0) + 1

    # 3. upsert 入库
    # 给每行加上 data_source_type（批次级）
    rows = parsed['rows']
    for row in rows:
        if 'data_source_type' not in row:
            row['data_source_type'] = data_source_type

    stats = upsert_rows(
        db=db,
        batch_id=batch.id,
        parsed_rows=rows,
        operator=user.get('username', 'system'),
    )

    # 4. 更新批次计数
    batch.imported_count = stats['created'] + stats['updated']
    batch.anomaly_count = (batch.anomaly_count or 0) + stats['orphaned']

    # 5. 固化校验和
    active_items = db.query(BoqItem).filter(
        BoqItem.import_batch_id == batch.id,
        BoqItem.active.is_(True),
    ).all()
    batch.checksum_count = len(active_items)
    batch.checksum_total = round(
        sum((item.total_num or 0) for item in active_items), 2
    )
    # checksum_hash：按 sequence 升序拼接关键字段后 SHA256
    import hashlib
    hash_input = '|'.join(
        f"{item.sequence}:{item.item_code or ''}:{item.item_name}:{item.total_num or 0}"
        for item in sorted(active_items, key=lambda x: x.sequence or 0)
    )
    batch.checksum_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

    # 6. 写审计日志
    log_audit(
        db=db,
        model="import_batch",
        res_id=batch.id,
        action="import",
        operator=user.get('username', 'system'),
        reason=f"导入批次 {batch_name}：新增 {stats['created']} / 更新 {stats['updated']} / 孤儿 {stats['orphaned']} / 回灌 {stats['preserved_manual']}",
        batch_id=batch.id,
    )

    db.commit()
    db.refresh(batch)

    # 清理临时文件
    try:
        os.unlink(safe_path)
    except OSError:
        pass

    return {
        'ok': True,
        'batch_id': batch.id,
        'batch_name': batch.name,
        'stats': stats,
        'checksum': {
            'count': batch.checksum_count,
            'total': batch.checksum_total,
            'hash': batch.checksum_hash[:16] + '...',
        },
        'archive_path': batch.archive_path,
    }


@router.get("/batches")
async def list_batches(
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批次列表（按创建时间倒序）。"""
    batches = db.query(ImportBatch).order_by(
        ImportBatch.id.desc()
    ).offset(offset).limit(limit).all()

    return {
        'total': db.query(ImportBatch).count(),
        'batches': [
            {
                'id': b.id,
                'biz_id': b.biz_id,
                'name': b.name,
                'source_file': b.source_file,
                'file_hash': b.file_hash[:16] + '...' if b.file_hash else None,
                'row_count': b.row_count,
                'imported_count': b.imported_count,
                'anomaly_count': b.anomaly_count,
                'data_source_type': b.data_source_type,
                'province': b.province,
                'active': b.active,
                'imported_at': b.imported_at.isoformat() if b.imported_at else None,
            }
            for b in batches
        ],
    }


@router.get("/batches/{batch_id}")
async def get_batch(
    batch_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批次详情。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    return {
        'id': batch.id,
        'biz_id': batch.biz_id,
        'name': batch.name,
        'source_file': batch.source_file,
        'file_hash': batch.file_hash,
        'row_count': batch.row_count,
        'imported_count': batch.imported_count,
        'skipped_count': batch.skipped_count,
        'anomaly_count': batch.anomaly_count,
        'data_source_type': batch.data_source_type,
        'province': batch.province,
        'price_period': batch.price_period.isoformat() if batch.price_period else None,
        'operator': batch.operator,
        'archive_path': batch.archive_path,
        'checksum_count': batch.checksum_count,
        'checksum_total': float(batch.checksum_total) if batch.checksum_total else None,
        'checksum_hash': batch.checksum_hash,
        'active': batch.active,
        'deleted_at': batch.deleted_at.isoformat() if batch.deleted_at else None,
        'imported_at': batch.imported_at.isoformat() if batch.imported_at else None,
    }


@router.get("/batches/{batch_id}/items")
async def list_batch_items(
    batch_id: int,
    limit: int = 100,
    offset: int = 0,
    active_only: bool = True,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批次明细行。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    query = db.query(BoqItem).filter(BoqItem.import_batch_id == batch_id)
    if active_only:
        query = query.filter(BoqItem.active.is_(True))
    query = query.order_by(BoqItem.sequence.asc())

    total = query.count()
    items = query.offset(offset).limit(limit).all()

    return {
        'batch_id': batch_id,
        'total': total,
        'items': [
            {
                'id': item.id,
                'biz_id': item.biz_id,
                'sequence': item.sequence,
                'item_code': item.item_code,
                'item_name': item.item_name,
                'item_feature': item.item_feature,
                'unit': item.unit,
                'unit_std': item.unit_std,
                'quantity': item.quantity,
                'unit_rate': item.unit_rate,
                'total': item.total,
                'std_name': item.std_name,
                'std_spec': item.std_spec,
                'anomaly_flag': item.anomaly_flag,
                'anomaly_reason': item.anomaly_reason,
                'active': item.active,
                'orphaned': item.orphaned,
            }
            for item in items
        ],
    }
