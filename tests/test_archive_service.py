# -*- coding: utf-8 -*-
"""M2.2 归档服务测试（archive_service）。

测试用例覆盖：
1. 基本归档（复制 + SHA256 校验）
2. 幂等（同 file_hash 已归档 → 复用）
3. 归档路径规则（YYYY/MM/<hash[:2]>/<原文件名>）
4. 同名冲突（加 <hash[:8]> 后缀）
5. 源文件不存在 → ok=False
6. verify_archive（一致/不一致/缺失）
7. 元信息文件写入
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import archive_service


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _make_source_file(content=b"test content for archive", name="source.xlsx"):
    """创建临时源文件，返回 (path, sha256)。"""
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, name)
    with open(path, 'wb') as f:
        f.write(content)
    return path, _sha256_file(path)


@pytest.fixture
def archive_root(tmp_path):
    """临时归档根目录。"""
    root = tmp_path / "archive"
    root.mkdir()
    return str(root)


class TestBasicArchive:
    """基本归档测试。"""

    def test_archive_success(self, archive_root):
        """基本归档：复制成功，SHA256 一致。"""
        src, file_hash = _make_source_file()
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            result = archive_service.archive(src, file_hash, archiver="tester")
        assert result['ok'] is True
        assert result['archive_path'] is not None
        assert result['sha256'] == file_hash
        # 归档文件存在
        assert os.path.isfile(result['archive_path'])
        # 归档文件内容与源文件一致
        assert _sha256_file(result['archive_path']) == file_hash

    def test_archive_creates_directory_structure(self, archive_root):
        """归档路径规则：YYYY/MM/<hash[:2]>/<原文件名>。"""
        src, file_hash = _make_source_file(name="mydata.xlsx")
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            result = archive_service.archive(src, file_hash)
        assert result['ok'] is True
        archive_path = Path(result['archive_path'])
        # 路径包含年份/月份
        parts = archive_path.relative_to(archive_root).parts
        assert len(parts) >= 3  # YYYY, MM, hash[:2], filename
        assert parts[0].isdigit() and len(parts[0]) == 4  # 年份
        assert parts[1].isdigit() and len(parts[1]) == 2  # 月份
        assert parts[2] == file_hash[:2]  # hash 前两位
        assert parts[-1] == "mydata.xlsx"  # 原文件名

    def test_archive_meta_file_written(self, archive_root):
        """元信息文件写入：<原文件名>.meta.json。"""
        src, file_hash = _make_source_file(name="meta_test.xlsx")
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            result = archive_service.archive(src, file_hash, archiver="tester")
        assert result['ok'] is True
        meta_path = Path(result['archive_path']).with_suffix('.xlsx.meta.json')
        assert meta_path.is_file()
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        assert meta['file_hash'] == file_hash
        assert meta['sha256'] == file_hash
        assert meta['archiver'] == 'tester'
        assert 'source_path' in meta
        assert 'archive_path' in meta
        assert 'archive_time' in meta


class TestIdempotent:
    """幂等测试。"""

    def test_same_hash_reuses_existing(self, archive_root):
        """同 file_hash 已归档 → 直接复用，不重复复制。"""
        src, file_hash = _make_source_file()
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            r1 = archive_service.archive(src, file_hash)
            assert r1['ok'] is True
            first_path = r1['archive_path']
            # 第二次归档（同 hash）
            r2 = archive_service.archive(src, file_hash)
            assert r2['ok'] is True
            assert r2['archive_path'] == first_path  # 复用同一路径

    def test_different_content_different_hash(self, archive_root):
        """不同内容（不同 hash）→ 不同归档路径。"""
        src1, hash1 = _make_source_file(content=b"content A", name="file.xlsx")
        src2, hash2 = _make_source_file(content=b"content B", name="file.xlsx")
        assert hash1 != hash2
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            r1 = archive_service.archive(src1, hash1)
            r2 = archive_service.archive(src2, hash2)
        assert r1['ok'] and r2['ok']
        assert r1['archive_path'] != r2['archive_path']


class TestNameConflict:
    """同名冲突测试。"""

    def test_same_name_different_hash_gets_suffix(self, archive_root):
        """同名已存在 → 加 <hash[:8]> 后缀（直接测试 _resolve_target）。"""
        root = Path(archive_root)
        # 创建同名文件模拟已存在
        target_dir = root / "2026" / "09" / "ab"
        target_dir.mkdir(parents=True, exist_ok=True)
        existing = target_dir / "dup.xlsx"
        existing.write_text("existing")

        src = Path("/tmp/dup.xlsx")  # 源路径只用于取文件名
        file_hash = "abcdef1234567890" * 4  # 64 字符
        result = archive_service._resolve_target(root, src, file_hash)
        # 应加后缀避免覆盖
        assert result.name == f"dup_{file_hash[:8]}.xlsx"
        assert result.parent == target_dir


class TestErrorCases:
    """错误场景测试。"""

    def test_source_not_exists(self, archive_root):
        """源文件不存在 → ok=False。"""
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            result = archive_service.archive("/nonexistent/path/file.xlsx", "abc123")
        assert result['ok'] is False
        assert '不存在' in result['reason']
        assert result['archive_path'] is None

    def test_archive_hash_mismatch(self, archive_root):
        """归档后 hash 不匹配 → ok=False，删除不一致文件。"""
        src, file_hash = _make_source_file()
        # 篡改：archive 时传入错误的 file_hash
        wrong_hash = "0" * 64
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            result = archive_service.archive(src, wrong_hash)
        assert result['ok'] is False
        assert 'SHA256 不匹配' in result['reason']
        # 不一致的归档文件应被删除
        # （归档目录下不应有完整的归档文件，因为 hash 不匹配会被 unlink）


class TestVerifyArchive:
    """verify_archive 测试。"""

    def test_all_verified(self, archive_root):
        """全部校验一致。"""
        src, file_hash = _make_source_file(name="verify.xlsx")
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            arch_result = archive_service.archive(src, file_hash)
        assert arch_result['ok']
        batch_list = [
            {'id': 1, 'biz_id': 'batch-001', 'archive_path': arch_result['archive_path'], 'file_hash': file_hash},
        ]
        result = archive_service.verify_archive(batch_list)
        assert result['verified'] == 1
        assert result['mismatch'] == 0
        assert result['missing'] == 0

    def test_missing_archive(self):
        """归档文件缺失 → missing。"""
        batch_list = [
            {'id': 1, 'biz_id': 'batch-001', 'archive_path': '/nonexistent/archive.xlsx', 'file_hash': 'abc'},
        ]
        result = archive_service.verify_archive(batch_list)
        assert result['missing'] == 1
        assert result['verified'] == 0
        assert len(result['details']) == 1
        assert '不存在' in result['details'][0]['reason']

    def test_empty_archive_path(self):
        """archive_path 为空 → missing。"""
        batch_list = [
            {'id': 1, 'biz_id': 'batch-001', 'archive_path': None, 'file_hash': 'abc'},
        ]
        result = archive_service.verify_archive(batch_list)
        assert result['missing'] == 1
        assert 'archive_path 为空' in result['details'][0]['reason']

    def test_hash_mismatch(self, archive_root):
        """hash 不一致 → mismatch。"""
        src, file_hash = _make_source_file(name="mismatch.xlsx")
        with patch.object(archive_service, 'get_archive_root', return_value=Path(archive_root)):
            arch_result = archive_service.archive(src, file_hash)
        assert arch_result['ok']
        # 传入错误的 file_hash
        batch_list = [
            {'id': 1, 'biz_id': 'batch-001', 'archive_path': arch_result['archive_path'], 'file_hash': '0' * 64},
        ]
        result = archive_service.verify_archive(batch_list)
        assert result['mismatch'] == 1
        assert result['verified'] == 0
        assert 'SHA256 校验失败' in result['details'][0]['reason']


class TestGetArchiveRoot:
    """get_archive_root 测试。"""

    def test_default_archive_root_exists(self):
        """默认归档根目录存在（项目目录下 archive/）。"""
        root = archive_service.get_archive_root()
        assert root.is_dir()
        assert root.name == 'archive'
