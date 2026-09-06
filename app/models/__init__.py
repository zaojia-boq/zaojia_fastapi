# -*- coding: utf-8 -*-
"""SQLAlchemy 模型包。

四核心模型（M1 §4.1-4.8）：
- BoqItem：清单项（核心，40+ 字段，A/B/C 分层）
- ImportBatch：导入批次（溯源 + 校验和 + 软删）
- MaterialDict：三级材料分类字典（小表，读多写少）
- AuditLog：不可变审计日志（append-only）

所有模型继承 app.models.base_mixin.Base。
"""
from app.models.base_mixin import Base, BizIdMixin, TimestampMixin
from app.models.boq_item import BoqItem
from app.models.import_batch import ImportBatch
from app.models.material_dict import MaterialDict
from app.models.audit_log import AuditLog

__all__ = [
    "Base",
    "BizIdMixin",
    "TimestampMixin",
    "BoqItem",
    "ImportBatch",
    "MaterialDict",
    "AuditLog",
]
