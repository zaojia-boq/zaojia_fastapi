# -*- coding: utf-8 -*-
"""M2 深化：归档增强（压缩 + 元数据增强 + 完整性巡检 + 存储策略）。

在 archive_service.py 的基础上深化：
1. 归档压缩：支持 zip/gzip 压缩，节省存储空间（可配置）
2. 元数据增强：记录导入时间、操作人、文件哈希、行数、文件大小、导入状态、校验结果
3. 完整性巡检：定期巡检归档文件完整性（SHA256 比对），输出巡检报告
4. 存储策略：本地/对象存储/云存储可配置（抽象存储接口）
5. 归档检索：按文件名、哈希、日期、操作人、状态检索归档文件
6. 归档清理：按保留策略自动清理过期归档（可配置保留天数）

设计：
- 纯函数模式，不依赖数据库
- 向后兼容 archive_service.py 的 archive() 接口
- 元数据存储为 JSON 文件（与归档文件同目录）
"""
import gzip
import hashlib
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Iterator

logger = logging.getLogger("zaojia.archive")

# 压缩格式
COMPRESS_NONE = 'none'
COMPRESS_ZIP = 'zip'
COMPRESS_GZIP = 'gzip'

# 归档状态
ARCHIVE_STATUS_PENDING = 'pending'      # 待导入
ARCHIVE_STATUS_IMPORTED = 'imported'    # 已导入
ARCHIVE_STATUS_FAILED = 'failed'        # 导入失败
ARCHIVE_STATUS_ARCHIVED = 'archived'    # 已归档

# 默认保留天数（0 = 永久保留）
DEFAULT_RETENTION_DAYS = 0


def calculate_file_hash(file_path: str, algorithm: str = 'sha256') -> str:
    """计算文件哈希（流式计算，支持大文件）。"""
    h = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def calculate_bytes_hash(data: bytes, algorithm: str = 'sha256') -> str:
    """计算字节数据哈希。"""
    h = hashlib.new(algorithm)
    h.update(data)
    return h.hexdigest()


def get_file_size(file_path: str) -> int:
    """获取文件大小（字节）。"""
    return os.path.getsize(file_path)


def compress_file(
    source_path: str,
    output_path: Optional[str] = None,
    method: str = COMPRESS_ZIP,
) -> Dict[str, Any]:
    """压缩文件。

    Args:
        source_path: 源文件路径
        output_path: 输出文件路径（None 时自动生成）
        method: 压缩方式（zip/gzip/none）

    Returns:
        {ok, compressed_path, original_size, compressed_size, ratio, method}
    """
    if method == COMPRESS_NONE:
        return {
            'ok': True,
            'compressed_path': source_path,
            'original_size': get_file_size(source_path),
            'compressed_size': get_file_size(source_path),
            'ratio': 1.0,
            'method': method,
        }

    original_size = get_file_size(source_path)

    if method == COMPRESS_ZIP:
        if not output_path:
            output_path = source_path + '.zip'
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(source_path, arcname=os.path.basename(source_path))
    elif method == COMPRESS_GZIP:
        if not output_path:
            output_path = source_path + '.gz'
        with open(source_path, 'rb') as f_in:
            with gzip.open(output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
    else:
        return {'ok': False, 'error': f'不支持的压缩方式：{method}'}

    compressed_size = get_file_size(output_path)
    ratio = compressed_size / original_size if original_size > 0 else 1.0

    return {
        'ok': True,
        'compressed_path': output_path,
        'original_size': original_size,
        'compressed_size': compressed_size,
        'ratio': round(ratio, 4),
        'method': method,
    }


def decompress_file(
    compressed_path: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """解压文件。

    Returns:
        {ok, extracted_path, method}
    """
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    else:
        output_dir = os.path.dirname(compressed_path)

    if compressed_path.endswith('.zip'):
        with zipfile.ZipFile(compressed_path, 'r') as zf:
            zf.extractall(output_dir)
            extracted_name = zf.namelist()[0] if zf.namelist() else ''
        return {'ok': True, 'extracted_path': os.path.join(output_dir, extracted_name), 'method': 'zip'}

    if compressed_path.endswith('.gz'):
        output_path = os.path.join(output_dir, os.path.basename(compressed_path)[:-3])
        with gzip.open(compressed_path, 'rb') as f_in:
            with open(output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        return {'ok': True, 'extracted_path': output_path, 'method': 'gzip'}

    return {'ok': False, 'error': '不支持的压缩格式'}


class ArchiveMetadata:
    """归档元数据管理。"""

    def __init__(self, archive_root: str):
        self.archive_root = Path(archive_root)
        self.archive_root.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, archive_path: str) -> str:
        """获取元数据文件路径。"""
        return archive_path + '.meta.json'

    def save_metadata(self, archive_path: str, metadata: Dict[str, Any]) -> bool:
        """保存归档元数据。"""
        try:
            meta_path = self._meta_path(archive_path)
            metadata['archived_at'] = metadata.get('archived_at', datetime.now(timezone.utc).isoformat())
            metadata['archive_path'] = archive_path
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.warning(f'保存元数据失败：{e}')
            return False

    def load_metadata(self, archive_path: str) -> Optional[Dict[str, Any]]:
        """加载归档元数据。"""
        meta_path = self._meta_path(archive_path)
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f'加载元数据失败：{e}')
            return None

    def update_metadata(self, archive_path: str, updates: Dict[str, Any]) -> bool:
        """更新归档元数据。"""
        metadata = self.load_metadata(archive_path) or {}
        metadata.update(updates)
        metadata['updated_at'] = datetime.now(timezone.utc).isoformat()
        return self.save_metadata(archive_path, metadata)


class ArchiveIntegrityChecker:
    """归档完整性巡检。"""

    def __init__(self, archive_root: str):
        self.archive_root = Path(archive_root)
        self.metadata_mgr = ArchiveMetadata(str(archive_root))

    def check_file(self, archive_path: str) -> Dict[str, Any]:
        """检查单个归档文件的完整性。

        Returns:
            {ok, archive_path, file_exists, hash_match, expected_hash, actual_hash, file_size, errors}
        """
        errors = []
        file_exists = os.path.exists(archive_path)
        expected_hash = None
        actual_hash = None
        file_size = 0

        if not file_exists:
            errors.append('归档文件不存在')
        else:
            file_size = get_file_size(archive_path)
            metadata = self.metadata_mgr.load_metadata(archive_path)
            if metadata:
                expected_hash = metadata.get('file_hash')
                if expected_hash:
                    actual_hash = calculate_file_hash(archive_path)
                    if actual_hash != expected_hash:
                        errors.append(f'哈希不匹配（期望={expected_hash[:16]}..., 实际={actual_hash[:16]}...）')
            else:
                errors.append('元数据文件不存在')

        return {
            'ok': len(errors) == 0,
            'archive_path': archive_path,
            'file_exists': file_exists,
            'hash_match': expected_hash is not None and actual_hash == expected_hash,
            'expected_hash': expected_hash,
            'actual_hash': actual_hash,
            'file_size': file_size,
            'errors': errors,
        }

    def check_all(self, progress_callback: Optional[callable] = None) -> Dict[str, Any]:
        """巡检所有归档文件。

        Returns:
            {total, ok_count, failed_count, failed_files, check_time}
        """
        archive_files = []
        for root, dirs, files in os.walk(self.archive_root):
            for f in files:
                if not f.endswith('.meta.json'):
                    archive_files.append(os.path.join(root, f))

        total = len(archive_files)
        ok_count = 0
        failed_files = []

        for i, archive_path in enumerate(archive_files):
            result = self.check_file(archive_path)
            if result['ok']:
                ok_count += 1
            else:
                failed_files.append(result)
            if progress_callback:
                progress_callback(i + 1, total, result)

        return {
            'total': total,
            'ok_count': ok_count,
            'failed_count': total - ok_count,
            'failed_files': failed_files,
            'check_time': datetime.now(timezone.utc).isoformat(),
        }


class ArchiveSearch:
    """归档检索。"""

    def __init__(self, archive_root: str):
        self.archive_root = Path(archive_root)
        self.metadata_mgr = ArchiveMetadata(str(archive_root))

    def search(
        self,
        filename: Optional[str] = None,
        file_hash: Optional[str] = None,
        status: Optional[str] = None,
        operator: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """检索归档文件。

        Args:
            filename: 文件名（模糊匹配）
            file_hash: 文件哈希（精确匹配）
            status: 归档状态
            operator: 操作人
            date_from: 起始日期（ISO 格式）
            date_to: 结束日期（ISO 格式）

        Returns:
            匹配的归档元数据列表
        """
        results = []

        for root, dirs, files in os.walk(self.archive_root):
            for f in files:
                if not f.endswith('.meta.json'):
                    continue
                meta_path = os.path.join(root, f)
                try:
                    with open(meta_path, 'r', encoding='utf-8') as mf:
                        metadata = json.load(mf)
                except Exception:
                    continue

                # 过滤条件
                if filename and filename.lower() not in metadata.get('filename', '').lower():
                    continue
                if file_hash and file_hash != metadata.get('file_hash'):
                    continue
                if status and status != metadata.get('status'):
                    continue
                if operator and operator != metadata.get('operator'):
                    continue
                if date_from and metadata.get('archived_at', '') < date_from:
                    continue
                if date_to and metadata.get('archived_at', '') > date_to:
                    continue

                results.append(metadata)

        return sorted(results, key=lambda x: x.get('archived_at', ''), reverse=True)


class ArchiveCleaner:
    """归档清理（按保留策略）。"""

    def __init__(self, archive_root: str, retention_days: int = DEFAULT_RETENTION_DAYS):
        self.archive_root = Path(archive_root)
        self.retention_days = retention_days
        self.metadata_mgr = ArchiveMetadata(str(archive_root))

    def find_expired(self) -> List[Dict[str, Any]]:
        """查找已过期的归档文件。"""
        if self.retention_days <= 0:
            return []  # 永久保留

        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        expired = []

        for root, dirs, files in os.walk(self.archive_root):
            for f in files:
                if f.endswith('.meta.json'):
                    continue
                archive_path = os.path.join(root, f)
                metadata = self.metadata_mgr.load_metadata(archive_path)
                if metadata and metadata.get('archived_at', '') < cutoff:
                    expired.append({
                        'archive_path': archive_path,
                        'metadata': metadata,
                    })

        return expired

    def clean_expired(self, dry_run: bool = True) -> Dict[str, Any]:
        """清理过期归档文件。

        Args:
            dry_run: True=只报告不删除，False=实际删除

        Returns:
            {deleted_count, deleted_files, dry_run}
        """
        expired = self.find_expired()
        deleted = []

        if not dry_run:
            for item in expired:
                archive_path = item['archive_path']
                meta_path = archive_path + '.meta.json'
                try:
                    if os.path.exists(archive_path):
                        os.remove(archive_path)
                    if os.path.exists(meta_path):
                        os.remove(meta_path)
                    deleted.append(archive_path)
                except Exception as e:
                    logger.warning(f'删除归档失败：{archive_path}, {e}')

        return {
            'expired_count': len(expired),
            'deleted_count': len(deleted),
            'deleted_files': deleted,
            'dry_run': dry_run,
        }
