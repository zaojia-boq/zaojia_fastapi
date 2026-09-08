# -*- coding: utf-8 -*-
"""审计落库（M1.4）。所有写操作落 audit_log 表（append-only）。

审计四元组：operator/reason/trace_id/timestamp（架构 §19.7）。
与 Odoo 版审计四元组对齐。

ADR-F005：请求级审计的 operator 必须是真实用户，不得恒为 anonymous。
修复点：security.get_current_user / pages.get_page_user 鉴权通过时
写入 request.state.username（与 scope["state"] 共享），中间件从该处读取。
"""
import logging
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware

from app.models.audit_log import AuditLog

logger = logging.getLogger("zaojia.audit")

# 动作常量
ACTION_CREATE = "create"
ACTION_WRITE = "write"
ACTION_SOFT_DELETE = "soft_delete"
ACTION_RESTORE = "restore"
ACTION_IMPORT = "import"
ACTION_EXPORT = "export"
ACTION_HARD_DELETE = "hard_delete"

_MAX_VALUE_LEN = 512

# 写操作方法集合（中间件审计范围）
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _truncate(value):
    """长文本截断到 512 字符，标注 [truncated]。"""
    if value is None:
        return None
    s = str(value)
    if len(s) > _MAX_VALUE_LEN:
        return s[:_MAX_VALUE_LEN] + " [truncated]"
    return s


def log_audit(db, model, res_id, action, operator="system", reason="",
              trace_id=None, field_name=None, old_value=None, new_value=None,
              batch_id=None):
    """写审计日志（落库）。

    返回 AuditLog 实例（已 add 到 session，调用方负责 flush/commit）。

    Args:
        db: SQLAlchemy Session
        model: 被操作模型名（如 "boq_item"）
        res_id: 记录 ID（软引用）
        action: 动作（ACTION_CREATE / ACTION_WRITE / ...）
        operator: 操作人（默认 "system"）
        reason: 变更原因（B 类字段变更必填）
        trace_id: 追踪 ID（未传时自动生成 UUID4）
        field_name: 变更字段（write 时逐字段记录）
        old_value: 变更前值（自动截断 512）
        new_value: 变更后值（自动截断 512）
        batch_id: 关联批次 ID（软引用）
    """
    entry = AuditLog(
        model=model,
        res_id=res_id,
        action=action,
        field_name=field_name,
        old_value=_truncate(old_value),
        new_value=_truncate(new_value),
        operator=operator or "system",
        reason=reason,
        trace_id=trace_id or str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        batch_id=batch_id,
    )
    db.add(entry)
    return entry


# 向后兼容别名（旧代码用 audit_log，新代码用 log_audit）
def audit_log(operator="system", action="", reason="", target="", **kwargs):
    """旧版接口兼容（M0 占位版签名）。

    新版请用 log_audit(db=..., model=..., res_id=..., action=...)。
    此别名仅用于 main.py 等尚未迁移的调用点，不写库。
    """
    logger.warning("audit_log() 是旧版兼容别名，不写库；请改用 log_audit()")
    return {
        "operator": operator,
        "action": action,
        "reason": reason,
        "target": target,
        "trace_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


class AuditMiddleware(BaseHTTPMiddleware):
    """请求级审计中间件。

    对所有写操作（POST/PUT/PATCH/DELETE）记录一条 http_request 审计日志。
    operator 从 request.state.username 读取（鉴权层写入），未认证时为 anonymous。

    审计四元组：operator（真实用户）/ reason（请求路径+方法）/ trace_id（请求ID）/ timestamp。
    """

    async def dispatch(self, request, call_next):
        if request.method not in _WRITE_METHODS:
            return await call_next(request)

        trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
        request.state.trace_id = trace_id

        response = await call_next(request)

        # call_next 之后读取 operator（get_current_user 在路由处理时写入 request.state.username）
        operator = getattr(request.state, "username", None) or "anonymous"

        # 异步落审计（不阻塞响应）
        try:
            # 从 app.state 获取 session factory（测试时注入测试库，生产用默认）
            session_factory = getattr(request.app.state, "db_session_factory", None)
            if session_factory is None:
                from app.db import SessionLocal
                session_factory = SessionLocal
            db = session_factory()
            try:
                log_audit(
                    db=db,
                    model="http_request",
                    res_id=None,
                    action=request.method.lower(),
                    operator=operator,
                    reason=f"{request.method} {request.url.path}",
                    trace_id=trace_id,
                )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("审计中间件落库失败")
            finally:
                db.close()
        except Exception:
            logger.exception("审计中间件初始化失败")

        return response
