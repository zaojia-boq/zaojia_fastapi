# -*- coding: utf-8 -*-
"""模型基类与 Mixin。

- Base：SQLAlchemy DeclarativeBase（所有模型继承）
- BizIdMixin：稳定业务 ID（UUID4，create 自动生成，不可变）
- TimestampMixin：创建/更新时间戳

设计来源：原 Odoo 版 zaojia.biz.mixin（架构 §19.5 / M1 §16.1）。
规则（写死，勿弱化）：
1. create 时若未显式传 biz_id，则自动生成 UUID4；
2. biz_id 唯一索引由各模型声明；
3. biz_id 一旦生成不可变。
"""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 SQLAlchemy 模型的基类。"""
    pass


class BizIdMixin:
    """稳定业务 ID Mixin（UUID4，不可变）。

    适用模型：BoqItem / ImportBatch / MaterialDict。
    内部仍用自增 id；未来 API / 智能体一律以 biz_id 为长期接口标识。
    """
    biz_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        comment='稳定业务 ID（UUID4）。create 自动生成、不可变。',
    )


class TimestampMixin:
    """创建/更新时间戳 Mixin。"""
    create_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment='创建时间',
    )
    write_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment='更新时间',
    )
