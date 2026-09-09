# -*- coding: utf-8 -*-
"""archive_service —— 原始文件归档 + 完整性校验（M2.2 实现）。

职责（M1 §8.5）：
1. 归档即复制：源文件只读打开，复制到归档目录（S1 源文件不变）；
2. 路径规则：<root>/YYYY/MM/<hash[:2]>/<原文件名>，同名加 <hash[:8]> 后缀；
3. 幂等：同 file_hash 已归档 → 直接复用，不重复复制；
4. 元信息：同目录写 <原文件名>.meta.json；
5. 校验：verify_archive() 遍历重算 SHA256，与 import_batch.file_hash 比对。

设计来源：原 Odoo 版 services/archive_service.py（算法 100% 继承，框架切换）。

边界（架构 §19.6）：
- 只接结构化参数、只返结构化信封 {ok, archive_path, sha256, reason?}；
- 不修改源文件（S1）；
- 不写库（调用方在 import 流程内编排时序）。
"""
import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.config import settings

logger = logging.getLogger("zaojia.archive")


def get_archive_root() -> Path:
    """解析归档根目录。

    优先级：settings.archive_root（env 配置）> 项目目录下 archive/。
    """
    root = getattr(settings, 'archive_root', None)
    if root:
        p = Path(root)
        if p.is_dir():
            return p
        logger.warning('归档根目录配置 %s 不是有效目录，回退默认', root)
    # 默认：项目目录下 archive/
    default = Path(settings.__class__.__module__).parent.parent / 'archive'
    # 用项目根目录（app/config.py 的上两级）
    default = Path(__file__).resolve().parent.parent.parent / 'archive'
    default.mkdir(parents=True, exist_ok=True)
    return default


def archive(
    source_path: str,
    file_hash: str,
    archiver: str = "system",
) -> Dict[str, Any]:
    """复制归档 + 校验 → envelope{ok, archive_path, sha256}。

    参数
    ----
    source_path : str —— 源文件绝对路径
    file_hash : str —— 源文件 SHA256（十六进制小写，用于幂等键和校验）
    archiver : str —— 归档操作人（写元信息用）

    返回
    ----
    dict : {
        'ok': bool,
        'archive_path': str | None,
        'sha256': str | None,
        'reason': str | None,
    }
    """
    src = Path(source_path)
    if not src.is_file():
        return {'ok': False, 'reason': f'源文件不存在: {source_path}', 'archive_path': None, 'sha256': None}

    root = get_archive_root()

    # 幂等：同一 file_hash 已归档 → 直接复用
    existing = _find_existing(root, file_hash)
    if existing is not None:
        logger.info('归档幂等：file_hash=%s 已存在 %s', file_hash[:16], existing)
        return {
            'ok': True,
            'archive_path': str(existing),
            'sha256': _compute_sha256(existing),
            'reason': None,
        }

    # 计算归档目标路径
    target = _resolve_target(root, src, file_hash)

    # 复制（保留元数据）
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    except OSError as e:
        return {'ok': False, 'reason': f'归档写入失败: {e}', 'archive_path': None, 'sha256': None}

    # 校验拷贝完整性
    actual_hash = _compute_sha256(target)
    if actual_hash != file_hash:
        logger.error('归档校验失败：hash 不匹配 %s vs %s', file_hash[:16], actual_hash[:16])
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            'ok': False,
            'reason': '归档校验失败：SHA256 不匹配（可能文件损坏）',
            'archive_path': None,
            'sha256': None,
        }

    # 写元信息
    _write_meta(target, src, file_hash, archiver)

    return {
        'ok': True,
        'archive_path': str(target),
        'sha256': actual_hash,
        'reason': None,
    }


def verify_archive(batch_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """遍历归档目录，重算 SHA256 并与批次 file_hash 比对。

    参数
    ----
    batch_list : list[dict] —— 每批含 archive_path / file_hash / id / biz_id

    返回
    ----
    dict : {
        'verified': int, 'mismatch': int, 'missing': int,
        'details': list[dict],
    }
    """
    result = {'verified': 0, 'mismatch': 0, 'missing': 0, 'details': []}
    for batch in batch_list:
        archive_path = batch.get('archive_path')
        if not archive_path:
            result['missing'] += 1
            result['details'].append({
                'batch_id': batch.get('id'),
                'biz_id': batch.get('biz_id'),
                'reason': 'archive_path 为空（归档失败或未归档）',
            })
            continue

        archive_file = Path(archive_path)
        if not archive_file.is_file():
            result['missing'] += 1
            result['details'].append({
                'batch_id': batch.get('id'),
                'biz_id': batch.get('biz_id'),
                'archive_path': str(archive_file),
                'reason': '归档文件不存在',
            })
            continue

        actual_hash = _compute_sha256(archive_file)
        expected_hash = batch.get('file_hash')
        if actual_hash != expected_hash:
            result['mismatch'] += 1
            result['details'].append({
                'batch_id': batch.get('id'),
                'biz_id': batch.get('biz_id'),
                'archive_path': str(archive_file),
                'expected_hash': expected_hash,
                'actual_hash': actual_hash,
                'reason': 'SHA256 校验失败（归档文件可能被篡改）',
            })
        else:
            result['verified'] += 1

    return result


# ------------------------------------------------------------------
# 内部辅助
# ------------------------------------------------------------------

def _resolve_target(root: Path, source_path: Path, file_hash: str) -> Path:
    """计算归档目标路径：<root>/YYYY/MM/<hash[:2]>/<原文件名>[_<hash[:8]>]。

    若目标已存在（同名），加 <hash[:8]> 后缀避免覆盖。
    """
    ts = datetime.now(timezone.utc)
    year_month = ts.strftime('%Y/%m')
    short_hash = file_hash[:2]
    filename = source_path.name
    base = root / year_month / short_hash / filename

    # 幂等检测：同名已存在 → 加后缀
    if base.exists():
        stem = base.stem
        suffix = base.suffix
        candidate = base.parent / f'{stem}_{file_hash[:8]}{suffix}'
        if candidate.exists():
            raise RuntimeError(f'归档路径冲突：请检查归档目录 {base.parent}')
        return candidate
    return base


def _find_existing(root: Path, file_hash: str) -> Optional[Path]:
    """检查是否已有同 hash 归档（幂等复用）。

    遍历归档目录的 *.meta.json，查找匹配 file_hash。
    """
    for meta_file in root.rglob('*.meta.json'):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            if meta.get('file_hash') == file_hash:
                archive_file = Path(meta.get('archive_path'))
                if archive_file.is_file():
                    return archive_file
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _compute_sha256(path: Path) -> str:
    """计算文件 SHA256（十六进制小写）。"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _write_meta(target_path: Path, source_path: Path, file_hash: str, archiver: str) -> None:
    """写元信息 JSON 到 <目标文件名>.meta.json。"""
    meta = {
        'source_path': str(source_path),
        'archive_path': str(target_path),
        'file_size': target_path.stat().st_size,
        'file_hash': file_hash,
        'sha256': file_hash,
        'archive_time': datetime.now(timezone.utc).isoformat(timespec='seconds') + 'Z',
        'archiver': archiver,
    }
    meta_path = target_path.with_suffix(target_path.suffix + '.meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.debug('归档元信息已写: %s', meta_path)
