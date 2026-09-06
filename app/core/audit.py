# -*- coding: utf-8 -*-
"""审计中间件。所有写操作落 audit_logs（operator/reason/trace_id/timestamp）。

与 Odoo 版审计四元组对齐，当前为日志占位，数据库表建好后替换为落库。
"""
import logging
import time
import uuid

logger = logging.getLogger("zaojia.audit")


def audit_log(operator: str, action: str, reason: str = "", target: str = ""):
    """写审计日志（占位：输出到日志；后续落 audit_logs 表）。"""
    entry = {
        "operator": operator,
        "action": action,
        "reason": reason,
        "target": target,
        "trace_id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    logger.info("AUDIT %s", entry)
    return entry
