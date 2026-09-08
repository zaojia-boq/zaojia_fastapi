# -*- coding: utf-8 -*-
"""标签分类模型（P3 体验增强）。

用户可自定义标签，对清单项进行分类标记，便于筛选和管理。
标签为全局共享（所有用户可见），条目-标签关联按用户隔离。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base_mixin import Base


class Tag(Base):
    """标签表。

    字段：
    - id: 主键
    - name: 标签名称（唯一）
    - color: 标签颜色（十六进制，如 #FF5733）
    - description: 标签描述（可选）
    - created_by: 创建者用户名
    - created_at: 创建时间
    """
    __tablename__ = "tag"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True, comment="标签名称")
    color = Column(String(16), nullable=False, default="#4D7CFE", comment="标签颜色")
    description = Column(String(256), nullable=True, comment="标签描述")
    created_by = Column(String(128), nullable=False, comment="创建者用户名")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="创建时间",
    )

    # 关系
    item_tags = relationship("ItemTag", back_populates="tag", cascade="all, delete-orphan")

    def to_dict(self):
        """转换为字典（API 输出）。"""
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ItemTag(Base):
    """条目-标签关联表。

    字段：
    - id: 主键
    - tag_id: 标签 ID（外键 → tag.id）
    - boq_item_id: 清单项 ID（外键 → boq_item.id）
    - username: 打标签的用户（用户级隔离）
    - created_at: 打标签时间
    """
    __tablename__ = "item_tag"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(
        Integer,
        ForeignKey("tag.id", ondelete="CASCADE"),
        nullable=False,
        comment="标签 ID",
    )
    boq_item_id = Column(
        Integer,
        ForeignKey("boq_item.id", ondelete="CASCADE"),
        nullable=False,
        comment="清单项 ID",
    )
    username = Column(String(128), nullable=False, index=True, comment="打标签的用户")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="打标签时间",
    )

    # 关系
    tag = relationship("Tag", back_populates="item_tags")

    # 唯一约束：同一用户对同一条目同一标签只能打一次
    __table_args__ = (
        UniqueConstraint("tag_id", "boq_item_id", "username", name="uq_item_tag_user"),
        Index("ix_item_tag_tag_item", "tag_id", "boq_item_id"),
    )

    def to_dict(self):
        """转换为字典（API 输出）。"""
        return {
            "id": self.id,
            "tag_id": self.tag_id,
            "boq_item_id": self.boq_item_id,
            "username": self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
