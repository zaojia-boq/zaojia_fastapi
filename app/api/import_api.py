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
# M2 深化模块
from data.file_parser import parse_file, validate_file_type, detect_file_type
from data.validation_engine import validate_rows, get_rule_templates
from data.archive_enhanced import compress_file, ArchiveMetadata, COMPRESS_ZIP
from data.field_mapper import auto_map_headers, apply_mapping_to_row, validate_mapping

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
    """解析文件（M2 深化：多格式支持 + 魔数校验）。

    支持 .xlsx/.xlsm/.xls/.csv，使用魔数校验防扩展名伪造。
    任何解析失败统一转 400（不泄漏堆栈）。
    """
    # M2 深化：魔数校验（防扩展名伪造）
    is_valid, file_type = validate_file_type(file_bytes, filename)
    if not is_valid:
        if file_type == 'unknown':
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型：{filename or '未知'}。支持格式：.xlsx/.xlsm/.xls/.csv",
            )
        if file_type == 'xls_no_xlrd':
            raise HTTPException(
                status_code=400,
                detail="解析 .xls 文件需要安装 xlrd：pip install xlrd==1.2.0",
            )

    # M2 深化：多格式解析（统一接口）
    try:
        parsed = parse_file(file_bytes=file_bytes, filename=filename, sheet=sheet)
        # 转换为 import_service.parse_excel 的格式（兼容现有代码）
        return _convert_to_legacy_format(parsed, file_bytes, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 —— 上传内容为不可信输入，统一降级为 400
        logger.warning("文件解析失败（%s）: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail=f"文件解析失败：{e}")


def _convert_to_legacy_format(parsed: dict, file_bytes: bytes, filename: str) -> dict:
    """将多格式解析器的输出转换为 import_service.parse_excel 的兼容格式。

    完全兼容原始 parse_excel 的输出格式，包括：
    - _num 数值字段（quantity_num/unit_rate_num/total_num）
    - item_code 规范化（调用 parse_gb_code）
    - unit_std 归一化（调用 normalize_unit）
    - anomaly_flag/anomaly_reason 异常标记
    - 章节/分部标题行过滤（无编码且无量价 → 跳过）
    """
    import hashlib
    from data.gb_code import parse_gb_code
    from data.unit_normalize import normalize_unit

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # 使用字段映射自动映射表头
    headers = parsed.get('headers', [])
    rows_raw = parsed.get('rows', [])
    mapping = auto_map_headers(headers)

    # 应用映射到每行，并转换为兼容格式
    rows = []
    skipped_count = 0
    anomaly_count = 0
    parsed_total = 0.0
    summary_total = None
    warnings = list(parsed.get('warnings', []))
    unrecognized = [h for h in headers if h and h not in mapping]

    for row_idx, row in enumerate(rows_raw):
        mapped = apply_mapping_to_row(row, headers, mapping)
        item_name = mapped.get('item_name')
        if not item_name or not str(item_name).strip():
            skipped_count += 1
            continue

        rec = {
            'sequence': row_idx + 1,
            'source_sheet': parsed.get('sheet_name', ''),
            'item_name': str(item_name).strip(),
        }
        row_warns = []

        # 合计行检测
        if any(kw in str(item_name) for kw in ('合计', '总计', '小计', '求和', '总结')):
            try:
                summary_total = float(mapped.get('total', 0) or 0)
            except (ValueError, TypeError):
                pass
            continue

        # 国标编码（保留原始值 + 规范化完整值）
        raw_code = mapped.get('gb_code')
        if raw_code is not None and str(raw_code).strip():
            code_raw = str(raw_code).strip()
            rec['item_code_raw'] = code_raw
            _code_9, code_full = parse_gb_code(code_raw)
            rec['item_code'] = code_full

        # 项目特征描述
        feat = mapped.get('item_feature')
        if feat is not None and str(feat).strip():
            rec['item_feature'] = str(feat).strip()

        # 计量单位 + 归一化
        unit = mapped.get('unit')
        if unit is not None and str(unit).strip():
            rec['unit'] = str(unit).strip()
            unit_std, warn = normalize_unit(unit)
            rec['unit_std'] = unit_std
            if warn:
                row_warns.append(f'计量单位未归一化: {unit}')

        # 数值字段（同时保留字符串和 _num 数值）
        for canon, numf in (
            ('quantity', 'quantity_num'),
            ('unit_rate', 'unit_rate_num'),
            ('total', 'total_num'),
            ('provisional_sum', 'provisional_sum_num'),
        ):
            v = mapped.get(canon)
            if v is None or str(v).strip() == '':
                continue
            rec[canon] = str(v).strip()
            try:
                fv = float(v)
                rec[numf] = fv
                if canon == 'total':
                    parsed_total += fv
            except (ValueError, TypeError):
                row_warns.append(f'{canon} 非数值: {v}')

        # 其余文本字段
        for canon in ('project_name', 'sub_division', 'ordinal', 'source_path'):
            v = mapped.get(canon)
            if v is not None and str(v).strip():
                rec[canon] = str(v).strip()

        # 章节/分部标题行：有名称但无编码且无量价 → 结构性行，跳过不入库
        if (not rec.get('item_code')
                and rec.get('quantity_num') is None
                and rec.get('unit_rate_num') is None
                and rec.get('total_num') is None):
            skipped_count += 1
            continue

        # 异常标记
        if row_warns:
            anomaly_count += 1
            rec['anomaly_flag'] = 'warning'
            rec['anomaly_reason'] = '；'.join(row_warns)[:500]
        else:
            rec['anomaly_flag'] = 'normal'

        for w in row_warns:
            warnings.append({
                'row': row_idx + 1, 'reason': w,
                'raw': rec.get('item_code_raw', ''),
                'suggestion': '导入后人工核对',
            })

        rows.append(rec)

    return {
        'file_hash': file_hash,
        'filename': filename,
        'sheet_name': parsed.get('sheet_name', ''),
        'file_type': parsed.get('file_type', 'unknown'),
        'rows': rows,
        'row_count': len(rows),
        'skipped_count': skipped_count,
        'anomaly_count': anomaly_count,
        'warnings': warnings,
        'parsed_total': round(parsed_total, 2),
        'summary_total': summary_total,
        'headers': headers,
        'field_mapping': mapping,
        'unrecognized_columns': unrecognized,
    }


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

    # 解析（M2 深化：多格式支持 + 魔数校验）
    parsed = _parse_or_400(file_bytes, file.filename, sheet)

    # M2 深化：导入校验报告（数据质量检查）
    validation_report = validate_rows(parsed['rows'], use_builtin=True)

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
    # M2 深化：多格式信息
    preview['file_type'] = parsed.get('file_type', 'unknown')
    preview['headers'] = parsed.get('headers', [])
    preview['field_mapping'] = parsed.get('field_mapping', {})
    preview['unrecognized_columns'] = parsed.get('unrecognized_columns', [])
    # M2 深化：校验报告
    preview['validation'] = {
        'can_import': validation_report.can_import,
        'error_count': validation_report.error_count,
        'warning_count': validation_report.warning_count,
        'info_count': validation_report.info_count,
        'valid_rows': validation_report.valid_rows,
        'total_rows': validation_report.total_rows,
        'error_rows': validation_report.to_dict().get('error_rows', []),
        'warning_rows': validation_report.to_dict().get('warning_rows', []),
        'summary_by_rule': validation_report.to_dict().get('summary_by_rule', {}),
        'results': [r.to_dict() for r in validation_report.results[:50]],  # 最多返回前 50 条
    }

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
        # M2 深化：归档后自动压缩（ZIP 格式，节省存储空间）
        try:
            compress_result = compress_file(
                source_path=archive_result['archive_path'],
                method=COMPRESS_ZIP,
            )
            if compress_result['ok']:
                batch.archive_path = compress_result['compressed_path']
                # M2 深化：保存增强元数据
                archive_root = os.path.dirname(compress_result['compressed_path'])
                meta_mgr = ArchiveMetadata(archive_root)
                meta_mgr.update_metadata(
                    compress_result['compressed_path'],
                    {
                        'filename': parsed.get('filename'),
                        'file_hash': parsed['file_hash'],
                        'operator': user.get('username', 'system'),
                        'status': 'imported',
                        'row_count': parsed['row_count'],
                        'file_type': parsed.get('file_type', 'unknown'),
                        'compressed': True,
                        'compression_method': COMPRESS_ZIP,
                        'original_size': compress_result.get('original_size', 0),
                        'compressed_size': compress_result.get('compressed_size', 0),
                        'compression_ratio': compress_result.get('ratio', 1.0),
                        'imported_at': datetime.now(timezone.utc).isoformat(),
                    },
                )
        except Exception as e:
            logger.warning(f"归档压缩失败（不阻断导入）: {e}")
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
