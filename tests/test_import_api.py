# -*- coding: utf-8 -*-
"""M2.3 导入向导 API 集成测试（import_api）。

测试用例覆盖：
1. POST /api/import/upload —— 上传 Excel，返回预览信封
2. POST /api/import/execute —— 执行导入（创建批次 + 归档 + upsert）
3. GET /api/import/batches —— 批次列表
4. GET /api/import/batches/{batch_id} —— 批次详情
5. GET /api/import/batches/{batch_id}/items —— 批次明细
6. 权限：未授权 → 401
"""
import io
import os
import tempfile

import openpyxl
import pytest

from app.config import settings

# 开发期 dev_token（与 .env 一致）
DEV_TOKEN = getattr(settings, 'dev_token', 'zaojia-dev-token-2026')
AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}

STANDARD_HEADER = [
    '序号', '项目编码', '项目名称', '项目特征描述',
    '计量单位', '工程量', '综合单价', '合价',
]


def _make_excel_bytes(rows):
    """创建内存 Excel → bytes。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def sample_excel():
    """标准测试 Excel（2 行数据 + 1 合计行）。"""
    return _make_excel_bytes([
        STANDARD_HEADER,
        [1, '010101001001', '挖一般土方', '土壤类别:二类土', 'm3', 100, 50.5, 5050],
        [2, '010101002001', '挖沟槽土方', '土壤类别:三类土', 'm3', 50, 60, 3000],
        ['', '', '合计', '', '', '', '', 8050],
    ])


class TestUpload:
    """上传解析测试。"""

    def test_upload_success(self, client, sample_excel):
        """上传 Excel → 返回预览信封，row_count=2（合计行不入库）。"""
        response = client.post(
            "/api/import/upload",
            headers=AUTH_HEADER,
            files={"file": ("test.xlsx", sample_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data['row_count'] == 2
        # 合计行不计入 skipped_count（单独记录 summary_total）
        assert data['parsed_total'] == 8050.0
        assert data['summary_total'] == 8050.0
        assert 'file_token' in data
        assert 'tmp_path' in data
        assert 'file_hash' in data

    def test_upload_requires_auth(self, client, sample_excel):
        """未授权上传 → 401。"""
        response = client.post(
            "/api/import/upload",
            files={"file": ("test.xlsx", sample_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == 401

    def test_upload_empty_file(self, client):
        """空文件 → 400。"""
        response = client.post(
            "/api/import/upload",
            headers=AUTH_HEADER,
            files={"file": ("empty.xlsx", b"", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == 400


class TestExecute:
    """执行导入测试。"""

    def test_execute_success(self, client, sample_excel):
        """上传 → 执行 → 创建批次 + upsert 成功。"""
        # 1. 上传
        upload_resp = client.post(
            "/api/import/upload",
            headers=AUTH_HEADER,
            files={"file": ("test.xlsx", sample_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert upload_resp.status_code == 200
        upload_data = upload_resp.json()
        file_token = upload_data['file_token']
        tmp_path = upload_data['tmp_path']

        # 2. 执行
        execute_resp = client.post(
            "/api/import/execute",
            headers=AUTH_HEADER,
            data={
                "file_token": file_token,
                "tmp_path": tmp_path,
                "data_source_type": "completed",
            },
        )
        assert execute_resp.status_code == 200
        exec_data = execute_resp.json()
        assert exec_data['ok'] is True
        assert 'batch_id' in exec_data
        assert 'stats' in exec_data
        assert exec_data['stats']['created'] == 2  # 2 行新增
        assert 'checksum' in exec_data
        assert exec_data['checksum']['count'] == 2

    def test_execute_missing_tmp_file(self, client):
        """执行时临时文件不存在 → 400。"""
        response = client.post(
            "/api/import/execute",
            headers=AUTH_HEADER,
            data={
                "file_token": "nonexistent",
                "tmp_path": "/nonexistent/path/file.xlsx",
            },
        )
        assert response.status_code == 400


class TestExecutePathTraversal:
    """路径穿越闸门（2026-09-06 审查修复 P0-1）。

    /execute 的 tmp_path 由客户端传入，修复前被 open()/归档/删除三处直接使用，
    可读取并归档任意文件（含 .env）、且在解析成功后删除原文件。
    """

    def test_reject_path_outside_tempdir(self, client):
        """临时目录之外的已存在文件 → 400，且不得被删除。"""
        outside = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_traversal_target.txt')
        with open(outside, 'w', encoding='utf-8') as f:
            f.write('SECRET')
        try:
            resp = client.post(
                "/api/import/execute",
                headers=AUTH_HEADER,
                data={
                    "file_token": "zaojia_import_abcdef0123456789_1700000000",
                    "tmp_path": outside,
                },
            )
            assert resp.status_code == 400
            assert os.path.exists(outside), "穿越目标文件不得被删除"
        finally:
            if os.path.exists(outside):
                os.remove(outside)

    def test_reject_filename_mismatch_inside_tempdir(self, client):
        """位于临时目录但文件名与 file_token 不匹配 → 400（防横向读取他人文件）。"""
        target = os.path.join(tempfile.gettempdir(), 'zj_other_upload.xlsx')
        with open(target, 'wb') as f:
            f.write(b'PK\x03\x04fake')
        try:
            resp = client.post(
                "/api/import/execute",
                headers=AUTH_HEADER,
                data={
                    "file_token": "zaojia_import_abcdef0123456789_1700000000",
                    "tmp_path": target,
                },
            )
            assert resp.status_code == 400
            assert os.path.exists(target)
        finally:
            if os.path.exists(target):
                os.remove(target)

    def test_reject_traversal_in_file_token(self, client):
        """file_token 携带 ../ 穿越字符 → 400。"""
        resp = client.post(
            "/api/import/execute",
            headers=AUTH_HEADER,
            data={
                "file_token": "zaojia_import_../../../../Windows/win_1234567890",
                "tmp_path": os.path.join(tempfile.gettempdir(), "x.xlsx"),
            },
        )
        assert resp.status_code == 400

    def test_non_excel_file_returns_400_not_500(self, client):
        """非 Excel 文件 → 400（修复前 BadZipFile 未捕获，直达 500）。"""
        resp = client.post(
            "/api/import/upload",
            headers=AUTH_HEADER,
            files={"file": ("bad.xlsx", b"this is not an excel file",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert resp.status_code == 400


class TestBatchList:
    """批次列表测试。"""

    def test_list_batches_empty(self, client):
        """无批次时返回空列表。"""
        response = client.get("/api/import/batches", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 0
        assert data['batches'] == []

    def test_list_batches_after_import(self, client, sample_excel):
        """导入后批次列表包含新批次。"""
        # 上传 + 执行
        upload_resp = client.post(
            "/api/import/upload",
            headers=AUTH_HEADER,
            files={"file": ("test.xlsx", sample_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        upload_data = upload_resp.json()
        client.post(
            "/api/import/execute",
            headers=AUTH_HEADER,
            data={"file_token": upload_data['file_token'], "tmp_path": upload_data['tmp_path']},
        )
        # 查询列表
        response = client.get("/api/import/batches", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 1
        assert data['batches'][0]['imported_count'] == 2


class TestBatchDetail:
    """批次详情测试。"""

    def test_get_batch_detail(self, client, sample_excel):
        """批次详情包含完整字段。"""
        upload_resp = client.post(
            "/api/import/upload",
            headers=AUTH_HEADER,
            files={"file": ("test.xlsx", sample_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        upload_data = upload_resp.json()
        exec_resp = client.post(
            "/api/import/execute",
            headers=AUTH_HEADER,
            data={"file_token": upload_data['file_token'], "tmp_path": upload_data['tmp_path']},
        )
        batch_id = exec_resp.json()['batch_id']

        response = client.get(f"/api/import/batches/{batch_id}", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data['id'] == batch_id
        assert data['row_count'] >= 2
        assert data['imported_count'] == 2
        assert data['checksum_count'] == 2
        assert data['checksum_total'] == 8050.0
        assert 'checksum_hash' in data

    def test_get_nonexistent_batch(self, client):
        """不存在的批次 → 404。"""
        response = client.get("/api/import/batches/99999", headers=AUTH_HEADER)
        assert response.status_code == 404


class TestBatchItems:
    """批次明细测试。"""

    def test_list_batch_items(self, client, sample_excel):
        """批次明细包含 2 行数据。"""
        upload_resp = client.post(
            "/api/import/upload",
            headers=AUTH_HEADER,
            files={"file": ("test.xlsx", sample_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        upload_data = upload_resp.json()
        exec_resp = client.post(
            "/api/import/execute",
            headers=AUTH_HEADER,
            data={"file_token": upload_data['file_token'], "tmp_path": upload_data['tmp_path']},
        )
        batch_id = exec_resp.json()['batch_id']

        response = client.get(f"/api/import/batches/{batch_id}/items", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 2
        items = data['items']
        assert items[0]['item_name'] == '挖一般土方'
        assert items[1]['item_name'] == '挖沟槽土方'
        assert items[0]['quantity'] == '100'
        assert items[0]['total'] == '5050'
