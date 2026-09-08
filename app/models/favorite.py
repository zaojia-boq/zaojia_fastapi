# -*- coding: utf-8 -*-
"""常用项收藏模型（P3 体验增强）。

用户可将常用清单项加入收藏，便于快速访问和复用。
收藏按 username 隔离（开发期通过 Cookie 模拟用户）。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base_mixin import Base


class UserFavorite(Base):
    """用户收藏表。

    字段：
    - id: 主键
    - username: 用户名（开发期从 Cookie/Token 获取，生产期从 OA SSO 获取）
    - boq_item_id: 收藏的清单项 ID（外键 → boq_item.id）
    - note: 收藏备注（可选，用户可添加说明）
    - created_at: 收藏时间
    """
    __tablename__ = "user_favorite"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(128), nullable=False, index=True, comment="用户名")
    boq_item_id = Column(
        Integer,
        ForeignKey("boq_item.id", ondelete="CASCADE"),
        nullable=False,
        comment="收藏的清单项 ID",
    )
    note = Column(String(500), nullable=True, comment="收藏备注")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="收藏时间",
    )

    # 关系（不使用 back_populates，避免循环导入问题）
    boq_item = relationship("BoqItem", foreign_keys=[boq_item_id])

    # 唯一约束：同一用户对同一条目只能收藏一次
    __table_args__ = (
        UniqueConstraint("username", "boq_item_id", name="uq_user_favorite_item"),
        Index("ix_user_favorite_username_created", "username", "created_at"),
    )

    def to_dict(self):
        """转换为字典（API 输出）。"""
        return {
            "id": self.id,
            "username": self.username,
            "boq_item_id": self.boq_item_id,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
