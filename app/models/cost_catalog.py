# -*- coding: utf-8 -*-
"""cost_catalog —— 独立成本库（M4 §3 落地，SQLAlchemy 版）。

设计来源：M4模块设计.md §3.2 字段表、§3.1 只读派生缓存定位。

核心定位：
- cost_catalog **不是第二真相源**，而是派生自 boq_item 的**只读预聚合缓存**
  （物化视图等价物）：不接收任何直接写，只能由迁移/刷新从 PG 重算生成，
  可随时从 boq_item 重建。真相源始终是唯一且不可重建的原始 Excel。
- 每条 match_key 一条记录，取最近 completed 行的标准化字段 + 所有 completed
  行的统计量（avg/min/max/sample_count）。
- B 类字段（std_name/std_spec/material_dict_id）继承 M1 §4.9 约束：
  迁移入库后不开放直接编辑，修正走专用向导 + reason 必填 + 审计日志。

字段 100% 继承 M4 设计稿 §3.2，仅 ORM 实现从 Odoo 切换为 SQLAlchemy 2.0。
"""
from datetime import date

from sqlalchemy import (
    String, Integer, Boolean, Date, DateTime, Numeric,
    ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_mixin import Base, BizIdMixin, TimestampMixin


class CostCatalog(Base, BizIdMixin, TimestampMixin):
    """独立成本库（只读派生缓存，按 match_key 聚合）。"""
    __tablename__ = "cost_catalog"

    # ------------------------------------------------------------------
    # 主键
    # ------------------------------------------------------------------
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ------------------------------------------------------------------
    # 聚合键（与 boq_item.match_key 一致）
    # ------------------------------------------------------------------
    match_key: Mapped[str] = mapped_column(
        String(256), nullable=False, unique=True, index=True,
        comment='聚合键，与 boq_item.match_key 一致；UNIQUE 保证每条 match_key 一条记录',
    )
    match_key_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default='code',
        comment='聚合键来源：dict/std/code/raw，与 boq_item.match_key_source 一致',
    )

    # ------------------------------------------------------------------
    # 标准化字段（B 类，禁静默覆盖，继承 M1 §4.9）
    # ------------------------------------------------------------------
    std_name: Mapped[str] = mapped_column(
        String(512), nullable=False, default='',
        comment='标准化名称（B 类不可重建字段，迁移后不开放直接编辑）',
    )
    std_spec: Mapped[str] = mapped_column(
        String(512), nullable=False, default='',
        comment='标准化规格（B 类不可重建字段）',
    )
    material_dict_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_dict.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment='物料分类关联（B 类；SET NULL：字典项删除时成本库保留，仅断开关联）',
    )

    # ------------------------------------------------------------------
    # 单位
    # ------------------------------------------------------------------
    unit_std: Mapped[str] = mapped_column(
        String(32), nullable=False, default='',
        comment='归一化单位',
    )

    # ------------------------------------------------------------------
    # 统计量（从 completed 行聚合，可刷新）
    # ------------------------------------------------------------------
    avg_rate: Mapped[float | None] = mapped_column(
        Numeric(16, 6), nullable=True,
        comment='历史均价（completed 行 unit_rate_num 的算术平均）',
    )
    min_rate: Mapped[float | None] = mapped_column(
        Numeric(16, 6), nullable=True,
        comment='历史最低价',
    )
    max_rate: Mapped[float | None] = mapped_column(
        Numeric(16, 6), nullable=True,
        comment='历史最高价',
    )
    sample_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment='参与统计的 completed 行数（unit_rate_num 非空）',
    )

    # ------------------------------------------------------------------
    # 最新记录溯源
    # ------------------------------------------------------------------
    latest_price: Mapped[float | None] = mapped_column(
        Numeric(16, 6), nullable=True,
        comment='最新一条 completed 行的单价（按 price_period 降序取首条）',
    )
    latest_period: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        comment='最新价格期',
    )
    latest_source: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment='最新记录来源（工程名 project_name）',
    )

    # ------------------------------------------------------------------
    # LanceDB 向量同步（P2，条件性启用）
    # ------------------------------------------------------------------
    embedding_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment='embedding 同步版本计数器；每次重建 LanceDB 索引 +1，用于检测漂移',
    )
    vector_sync_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment='PG 已更新但 LanceDB 向量未同步标记（写 PG 成功、向量失败时的补偿位点）',
    )

    # ------------------------------------------------------------------
    # 迁移溯源
    # ------------------------------------------------------------------
    migration_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batch.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment='迁移批次溯源（最近一次迁移该记录的 import_batch.id）',
    )

    # ------------------------------------------------------------------
    # 软删除
    # ------------------------------------------------------------------
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
        comment='软删除标记；cost_catalog 不物理删除，刷新时重建',
    )

    # ------------------------------------------------------------------
    # 关系
    # ------------------------------------------------------------------
    material_dict = relationship("MaterialDict", backref="cost_catalog_items", lazy="joined")
    migration_batch = relationship("ImportBatch", backref="cost_catalog_migrations", lazy="joined")

    # ------------------------------------------------------------------
    # 索引（match_key/material_dict_id/migration_batch_id 已在列定义加 index=True）
    # ------------------------------------------------------------------
    __table_args__ = (
        Index("ix_cost_catalog_std_name", "std_name"),
        Index("ix_cost_catalog_unit_std", "unit_std"),
    )

    def __repr__(self) -> str:
        return (
            f"<CostCatalog id={self.id} match_key={self.match_key!r} "
            f"std_name={self.std_name!r} avg={self.avg_rate} n={self.sample_count}>"
        )
