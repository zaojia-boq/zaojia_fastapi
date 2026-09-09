# -*- coding: utf-8 -*-
"""硬删闸门测试（C1 门禁补齐）。

验证硬删四道锁：
1. 管理员权限（require_role ROLE_ADMIN）
2. 名称二次确认（confirm_name 必须与批次名一致）
3. 30 天回收站宽限期（软删后 30 天内禁止硬删）
4. CSV 快照 fail-closed（快照导出失败必须拒绝物理删除）

AGENTS.md 登记：改动删除/回收站逻辑后必跑本文件。
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from app.config import settings
from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem

DEV_TOKEN = getattr(settings, 'dev_token', 'zaojia-dev-token-2026')
AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}


def _make_batch(db_session, name="测试批次", deleted_at=None):
    batch = ImportBatch(
        name=name,
        source_file="test.xlsx",
        file_hash="abc123",
        row_count=1,
        deleted_at=deleted_at,
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def _make_item(db_session, batch_id, name="镀锌钢管", code="030801001001"):
    item = BoqItem(
        import_batch_id=batch_id,
        item_code=code,
        item_name=name,
        item_feature="DN100",
        unit="m",
        quantity=100,
        unit_rate=78.5,
        total=7850,
        data_source_type="completed",
        province="辽宁",
        match_key_source="code",
        sequence=1,
    )
    db_session.add(item)
    db_session.flush()
    return item


class TestHardDeleteGate:
    """硬删闸门测试。"""

    def test_snapshot_failure_rejects_hard_delete(self, client, db_session):
        """C1 核心：CSV 快照导出失败时，硬删必须被拒绝（fail-closed），批次仍可查。"""
        batch = _make_batch(db_session, name="快照失败测试")
        _make_item(db_session, batch.id)

        # monkeypatch _export_snapshot 返回 None（模拟快照导出失败）
        with patch("app.api.batch._export_snapshot", return_value=None):
            resp = client.post(
                f"/api/import/batches/{batch.id}/hard-delete",
                json={"confirm_name": "快照失败测试"},
                headers=AUTH_HEADER,
            )

        # 断言：返回 500（快照失败拒绝硬删）
        assert resp.status_code == 500
        assert "快照导出失败" in resp.json()["detail"]

        # 断言：批次仍然存在（物理删除未执行）
        batch_after = db_session.get(ImportBatch, batch.id)
        assert batch_after is not None
        assert batch_after.name == "快照失败测试"

    def test_name_mismatch_rejects_hard_delete(self, client, db_session):
        """名称确认不一致时返回 400。"""
        batch = _make_batch(db_session, name="正确名称")

        resp = client.post(
            f"/api/import/batches/{batch.id}/hard-delete",
            json={"confirm_name": "错误名称"},
            headers=AUTH_HEADER,
        )

        assert resp.status_code == 400
        assert "不一致" in resp.json()["detail"]

    def test_batch_not_found_returns_404(self, client, db_session):
        """批次不存在返回 404。"""
        resp = client.post(
            "/api/import/batches/999999/hard-delete",
            json={"confirm_name": "不存在"},
            headers=AUTH_HEADER,
        )

        assert resp.status_code == 404

    def test_grace_period_rejects_hard_delete(self, client, db_session):
        """30 天回收站宽限期内禁止硬删。"""
        # 软删时间设为 10 天前（在 30 天宽限期内）
        deleted_at = datetime.now(timezone.utc) - timedelta(days=10)
        batch = _make_batch(db_session, name="宽限期测试", deleted_at=deleted_at)

        resp = client.post(
            f"/api/import/batches/{batch.id}/hard-delete",
            json={"confirm_name": "宽限期测试"},
            headers=AUTH_HEADER,
        )

        assert resp.status_code == 400
        assert "宽限期" in resp.json()["detail"]

    def test_hard_delete_success_with_snapshot(self, client, db_session, tmp_path):
        """快照导出成功时，硬删正常执行。"""
        batch = _make_batch(db_session, name="正常删除测试")
        _make_item(db_session, batch.id)

        # monkeypatch _export_snapshot 返回临时文件路径（模拟快照成功）
        snapshot_file = tmp_path / "snapshot.csv"
        snapshot_file.write_text("test", encoding="utf-8")

        with patch("app.api.batch._export_snapshot", return_value=str(snapshot_file)):
            resp = client.post(
                f"/api/import/batches/{batch.id}/hard-delete",
                json={"confirm_name": "正常删除测试"},
                headers=AUTH_HEADER,
            )

        # 断言：硬删成功
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 断言：批次已被物理删除
        batch_after = db_session.get(ImportBatch, batch.id)
        assert batch_after is None

    def test_snapshot_failure_with_annotated_items(self, client, db_session):
        """含人工标注（B 类字段）的批次，快照失败时更应拒绝（B 类闸门）。"""
        batch = _make_batch(db_session, name="含标注测试")
        # 创建含人工标注的清单项（std_name 非空 = B 类字段已填）
        item = _make_item(db_session, batch.id, name="标注项")
        item.std_name = "标准化名称"

        with patch("app.api.batch._export_snapshot", return_value=None):
            resp = client.post(
                f"/api/import/batches/{batch.id}/hard-delete",
                json={"confirm_name": "含标注测试"},
                headers=AUTH_HEADER,
            )

        assert resp.status_code == 500
        assert "人工标注" in resp.json()["detail"]

        # 批次和标注项都未被删除
        batch_after = db_session.get(ImportBatch, batch.id)
        assert batch_after is not None
