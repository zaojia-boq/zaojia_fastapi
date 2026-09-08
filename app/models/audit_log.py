# -*- coding: utf-8 -*-
"""audit_log —— 不可变审计日志（M1 §4.8 / §5.1 落地，SQLAlchemy 版）。

设计来源：原 Odoo 版 zaojia.audit.log。

append-only 三重保障（M1 §4.8）：
1. 模型层：SQLAlchemy 事件监听禁止 update/delete（before_update/before_delete 抛异常）；
2. 权限层：三角色均无 audit_log 写权限（M1.5 实现）；
3. 数据库层：REVOKE UPDATE/DELETE（生产环境，M2 部署时配置）。

本模型不建任何外键：model+res_id 为软引用（M1 §5.1）——原记录被物理删除
后日志仍须留存，外键会连带删掉证据。

审计四元组：operator/reason/trace_id/timestamp（架构 §19.7）。
"""
from datetime import datetime, timezone

from sqlalchemy import String, Text, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import event

from app.models.base_mixin import Base


class AuditLog(Base):
    """审计日志（append-only，不可修改不可删除）。"""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    model: Mapped[str | None] = mapped_column(
        String(100), index=True, comment='被操作模型（如 boq_item）',
    )
    res_id: Mapped[int | None] = mapped_column(Integer, comment='记录 ID（软引用，不建外键）')
    action: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment='动作（create/write/soft_delete/restore/import/export/hard_delete）',
    )
    field_name: Mapped[str | None] = mapped_column(String(100), comment='变更字段（write 时逐字段记）')
    old_value: Mapped[str | None] = mapped_column(Text, comment='变更前（截断 512）')
    new_value: Mapped[str | None] = mapped_column(Text, comment='变更后（截断 512）')
    operator: Mapped[str | None] = mapped_column(
        String(100), comment='操作人（OA 用户名，审计四元组之一）',
    )
    reason: Mapped[str | None] = mapped_column(
        Text, comment='变更原因（B 类字段变更必须人工填写，审计四元组之一）',
    )
    trace_id: Mapped[str | None] = mapped_column(
        String(64), comment='追踪 ID（请求级，审计四元组之一）',
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
        comment='时间（审计四元组之一）',
    )
    batch_id: Mapped[int | None] = mapped_column(
        Integer, comment='关联批次 ID（软引用，不建外键）',
    )

    __table_args__ = (
        Index("ix_audit_log_model_res", "model", "res_id"),
    )

    def __repr__(self):
        return f"<AuditLog id={self.id} action={self.action!r} model={self.model!r}>"


# ------------------------------------------------------------------
# append-only：SQLAlchemy 事件监听禁止 update/delete
# ------------------------------------------------------------------
@event.listens_for(AuditLog, "before_update")
def _audit_log_before_update(mapper, connection, target):
    """禁止修改审计日志（append-only）。"""
    raise PermissionError("审计日志为 append-only，禁止修改已有记录。")


@event.listens_for(AuditLog, "before_delete")
def _audit_log_before_delete(mapper, connection, target):
    """禁止删除审计日志（append-only）。"""
    raise PermissionError("审计日志为 append-only，禁止删除记录。")
