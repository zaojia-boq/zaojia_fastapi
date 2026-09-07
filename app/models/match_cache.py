# -*- coding: utf-8 -*-
"""匹配结果缓存表（M3 性能优化）。

后台预匹配：导入完成后异步计算所有待匹配条目的 Top-N 候选，
存入此表。匹配确认页面优先从缓存读取，避免实时计算 O(N×M)。

设计：
- 每个 boq_item_id 对应一条缓存记录（Top-5 候选 JSON）
- cache_version 用于字典变更后失效缓存
- computed_at 用于判断缓存是否过期（默认 24 小时）
"""
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base


CACHE_TTL_HOURS = 24  # 缓存有效期（小时）


class MatchCache(Base):
    """匹配结果缓存。"""
    __tablename__ = "match_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    boq_item_id = Column(Integer, nullable=False, index=True, comment="清单项 ID")
    candidates = Column(JSONB, nullable=False, comment="Top-N 候选列表（JSON）")
    top1_score = Column(Integer, nullable=True, comment="Top-1 分数（用于快速筛选高置信）")
    cache_version = Column(String(32), nullable=False, default="v1", comment="缓存版本（字典变更后失效）")
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="计算时间")

    __table_args__ = (
        Index("ix_match_cache_boq_item", "boq_item_id"),
        Index("ix_match_cache_top1_score", "top1_score"),
    )

    def is_expired(self, ttl_hours: int = CACHE_TTL_HOURS) -> bool:
        """判断缓存是否过期。"""
        if not self.computed_at:
            return True
        return datetime.utcnow() - self.computed_at > timedelta(hours=ttl_hours)

    def to_dict(self) -> dict:
        """转为字典。"""
        return {
            "id": self.id,
            "boq_item_id": self.boq_item_id,
            "candidates": self.candidates,
            "top1_score": self.top1_score,
            "cache_version": self.cache_version,
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
        }
