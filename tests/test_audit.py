# -*- coding: utf-8 -*-
"""M1.4 审计落库测试（S5/S9 安全用例）。

S5：所有写操作有审计记录
S9：审计四元组完整（operator/reason/trace_id/timestamp）

运行：
    python.exe -m pytest tests/test_audit.py -v
"""
import pytest

from app.config import settings
from app.models import AuditLog, BoqItem, ImportBatch
from app.core.audit import log_audit, ACTION_CREATE, ACTION_WRITE, ACTION_SOFT_DELETE


class TestAuditLogDirect:
    """log_audit 函数直接测试。"""

    def test_log_audit_creates_record(self, db_session):
        """S5：log_audit 创建审计记录。"""
        entry = log_audit(
            db=db_session,
            model="boq_item",
            res_id=1,
            action=ACTION_CREATE,
            operator="test_user",
            reason="测试创建",
        )
        db_session.flush()

        assert entry.id is not None
        assert entry.model == "boq_item"
        assert entry.res_id == 1
        assert entry.action == "create"
        assert entry.operator == "test_user"
        assert entry.reason == "测试创建"

    def test_s9_audit_quartet_complete(self, db_session):
        """S9：审计四元组完整（operator/reason/trace_id/timestamp）。"""
        entry = log_audit(
            db=db_session,
            model="boq_item",
            res_id=1,
            action=ACTION_WRITE,
            operator="user_a",
            reason="修改 B 类字段",
            trace_id="trace-abc-123",
        )
        db_session.flush()

        # 四元组全部非空
        assert entry.operator == "user_a"           # operator
        assert entry.reason == "修改 B 类字段"       # reason
        assert entry.trace_id == "trace-abc-123"    # trace_id
        assert entry.timestamp is not None            # timestamp

    def test_trace_id_auto_generated_when_not_provided(self, db_session):
        """trace_id 未传时自动生成 UUID4。"""
        entry = log_audit(
            db=db_session,
            model="boq_item",
            res_id=1,
            action=ACTION_CREATE,
            operator="user",
        )
        db_session.flush()

        assert entry.trace_id is not None
        # UUID4 格式
        parts = entry.trace_id.split("-")
        assert len(parts) == 5

    def test_operator_defaults_to_system(self, db_session):
        """operator 未传时默认为 "system"。"""
        entry = log_audit(
            db=db_session,
            model="boq_item",
            res_id=1,
            action=ACTION_CREATE,
        )
        db_session.flush()

        assert entry.operator == "system"

    def test_long_text_truncated(self, db_session):
        """长文本自动截断到 512 字符。"""
        long_text = "x" * 1000
        entry = log_audit(
            db=db_session,
            model="boq_item",
            res_id=1,
            action=ACTION_WRITE,
            old_value=long_text,
            new_value=long_text,
        )
        db_session.flush()

        assert len(entry.old_value) <= 512 + len(" [truncated]")
        assert "[truncated]" in entry.old_value

    def test_field_level_audit(self, db_session):
        """字段级审计：write 时逐字段记录 field_name + old/new value。"""
        entry = log_audit(
            db=db_session,
            model="boq_item",
            res_id=42,
            action=ACTION_WRITE,
            field_name="std_name",
            old_value="电缆",
            new_value="电力电缆",
            operator="estimator",
            reason="标准化标注",
        )
        db_session.flush()

        assert entry.field_name == "std_name"
        assert entry.old_value == "电缆"
        assert entry.new_value == "电力电缆"

    def test_soft_delete_audit(self, db_session):
        """软删除审计记录。"""
        entry = log_audit(
            db=db_session,
            model="import_batch",
            res_id=10,
            action=ACTION_SOFT_DELETE,
            operator="admin",
            reason="批次软删除进回收站",
            batch_id=10,
        )
        db_session.flush()

        assert entry.action == "soft_delete"
        assert entry.batch_id == 10


class TestAuditLogAppendOnly:
    """审计日志 append-only 验证（与 test_models.py 互补）。"""

    def test_query_audit_logs_by_model(self, db_session):
        """按 model 字段查询审计日志（复合索引验证）。"""
        for i in range(3):
            log_audit(db=db_session, model="boq_item", res_id=i, action="create", operator="u1")
        log_audit(db=db_session, model="import_batch", res_id=1, action="create", operator="u1")
        db_session.flush()

        # 按 model 查询
        boq_logs = db_session.query(AuditLog).filter(AuditLog.model == "boq_item").all()
        assert len(boq_logs) == 3

        batch_logs = db_session.query(AuditLog).filter(AuditLog.model == "import_batch").all()
        assert len(batch_logs) == 1

    def test_audit_log_persists_after_target_deleted(self, db_session):
        """软引用验证：目标记录删除后审计日志仍留存（不建外键）。"""
        batch = ImportBatch(name="临时批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        # 写审计日志
        log_audit(
            db=db_session,
            model="import_batch",
            res_id=batch.id,
            action="create",
            operator="u1",
        )
        db_session.flush()

        # 删除批次记录（模拟物理删除）
        batch_id = batch.id
        db_session.delete(batch)
        db_session.flush()

        # 审计日志仍在（软引用，不级联删除）
        logs = db_session.query(AuditLog).filter(
            AuditLog.model == "import_batch",
            AuditLog.res_id == batch_id,
        ).all()
        assert len(logs) == 1


class TestAuditMiddlewareOperator:
    """审计中间件四元组之「谁」（2026-09-06 审查修复 P1-1）。

    修复前 AuditMiddleware 读 scope["state"]["username"]，但全库无任何写入点，
    请求级审计的 operator 恒为 anonymous，ADR-F005 四元组中「谁」失效。
    修复：security.get_current_user / pages.get_page_user 鉴权通过时写入
    request.state.username（与 scope["state"] 共享）。
    """
    DEV_TOKEN = getattr(settings, 'dev_token', 'zaojia-dev-token-2026')
    AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}

    def test_middleware_records_real_operator(self, client, db_session):
        """POST 请求经中间件落审计时，operator 必须是真实用户而非 anonymous。"""
        resp = client.post("/api/admin/audit-test", headers=self.AUTH_HEADER)
        assert resp.status_code == 200

        db_session.expire_all()
        rows = db_session.query(AuditLog).filter(
            AuditLog.model == "http_request",
        ).all()

        assert rows, "审计中间件应写入一条 http_request 记录"
        operators = {r.operator for r in rows}
        assert "anonymous" not in operators, \
            f"operator 不得为 anonymous（说明 state.username 未写入）：{operators}"
        assert operators == {"dev_admin"}, f"实际 operator: {operators}"

    def test_unauthenticated_write_still_audited_as_anonymous(self, client, db_session):
        """未带令牌的写请求：仍被拒绝，中间件审计记为 anonymous（fail-closed 语义）。"""
        resp = client.post("/api/admin/audit-test")
        assert resp.status_code == 401

        db_session.expire_all()
        rows = db_session.query(AuditLog).filter(
            AuditLog.model == "http_request",
            AuditLog.operator == "anonymous",
        ).all()
        assert rows, "未认证写请求应留下 anonymous 审计痕迹（可追溯攻击尝试）"
