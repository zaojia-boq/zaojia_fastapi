# -*- coding: utf-8 -*-
"""boq_item —— 核心清单项（M1 §4.1 / §4.7 落地，SQLAlchemy 版）。

设计来源：原 Odoo 版 zaojia.boq.item（M1模块设计.md §4.1 字段表、§4.3 存储约定、
§4.7 数据性质、§4.9 数据分层 A/B/C、§16.1 稳定业务 ID）。

字段 100% 继承 Odoo 版，仅 ORM 实现从 Odoo models.Model 切换为 SQLAlchemy 2.0。
表名去掉 zaojia_boq_ 前缀：zaojia_boq_boq_item → boq_item。

注意：
- match_key / match_key_source / aggregate_id：M1.2 实现计算逻辑（委托 data.gb_code.compute_match_key），
  M1.1 先定义为普通列。
- data_source_type：nullable=False 且无默认值（M1 §4.7 v6.5 强化），任何 create 必须显式带值，
  防绕过向导把待审/控制价混入历史均价。
- B 类字段（std_name/std_spec/material_dict_id/anomaly_flag/anomaly_reason/data_source_type）
  禁静默覆盖，分层常量见 data/field_spec.py B_FIELDS。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    String, Text, Integer, Boolean, Date, DateTime, Numeric, JSON,
    ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import event

from app.models.base_mixin import Base, BizIdMixin, TimestampMixin
from data.gb_code import compute_match_key, parse_gb_code


class BoqItem(Base, BizIdMixin, TimestampMixin):
    """造价清单项（核心模型）。"""
    __tablename__ = "boq_item"

    # ------------------------------------------------------------------
    # 主键
    # ------------------------------------------------------------------
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ------------------------------------------------------------------
    # 溯源（批次 / 层级）
    # ------------------------------------------------------------------
    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment='溯源批次。RESTRICT：批次物理删除时若有明细行将被 DB 拒绝（防误删）；'
                '批次的「失效/删除」统一走软删 active=False，明细行自然保留。',
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("boq_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment='父级（层级折叠）',
    )
    depth: Mapped[int | None] = mapped_column(Integer, nullable=True, comment='层级深度')
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment='行序（导入时 = Excel 物理行号，保证还原原始顺序）',
    )

    # ------------------------------------------------------------------
    # 基本辨识
    # ------------------------------------------------------------------
    project_name: Mapped[str | None] = mapped_column(String, index=True, comment='工程名称')
    sub_division: Mapped[str | None] = mapped_column(String, comment='子分部')
    province: Mapped[str | None] = mapped_column(String, comment='地区')
    price_period: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        comment='价格期（存储约定：一律存当月 1 日，如 2026-03-01）',
    )
    ordinal: Mapped[str | None] = mapped_column(String, comment='清单内行号')
    item_code: Mapped[str | None] = mapped_column(
        String, index=True,
        comment='项目编码（国标 9 位 / 12 位，入库保留完整编码用于溯源，匹配时取前 9 位）',
    )
    item_code_raw: Mapped[str | None] = mapped_column(
        String, comment='编码原始值（始终保留单元格原始字符串，含前导 0 / 异常长度）',
    )
    item_code_version: Mapped[str | None] = mapped_column(
        String(20), index=True, default='unknown',
        comment='清单版本（2013/2024/unknown）',
    )
    item_name: Mapped[str] = mapped_column(String, nullable=False, index=True, comment='项目名称')
    item_feature: Mapped[str | None] = mapped_column(Text, comment='项目特征描述')
    unit: Mapped[str | None] = mapped_column(String, comment='计量单位')
    unit_std: Mapped[str | None] = mapped_column(
        String, index=True,
        comment='归一化单位（A 类可重建，导入期经 data.unit_normalize 写入）',
    )

    # ------------------------------------------------------------------
    # 量价（文本保真 + 数值列，M1 §4.4 三条纪律）
    # ------------------------------------------------------------------
    quantity: Mapped[str | None] = mapped_column(String, comment='工程量（文本保真）')
    quantity_num: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), comment='工程量（数值）')
    unit_rate: Mapped[str | None] = mapped_column(String, comment='综合单价（文本保真）')
    unit_rate_num: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), comment='综合单价（数值）')
    total: Mapped[str | None] = mapped_column(String, comment='合价（文本保真）')
    total_num: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), comment='合价（数值）')
    provisional_sum: Mapped[str | None] = mapped_column(String, comment='暂列金额/暂估价（文本保真）')
    provisional_sum_num: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), comment='暂列金额/暂估价（数值）')

    # ------------------------------------------------------------------
    # 标准化（B 类 · 不可重建，M1 §4.9）
    # ------------------------------------------------------------------
    std_name: Mapped[str | None] = mapped_column(String, comment='标准化项目名称（B 类，禁静默覆盖）')
    std_spec: Mapped[str | None] = mapped_column(String, comment='标准化规格（B 类，禁静默覆盖）')
    material_dict_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_dict.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment='物料分类（B 类，三级材料分类字典关联，仅人工确认后写入；字典项删改时明细行保留）',
    )

    # ------------------------------------------------------------------
    # 数据性质 / 聚合键（M1 §4.7）
    # ------------------------------------------------------------------
    data_source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment='数据性质（completed/control_price/bid_price/pending_review/info_price）。'
                'nullable=False 无默认值：create 必须显式带值，防绕过向导把待审/控制价混入历史均价。'
                '统计默认域只取 completed；pending_review 永不进历史均价。',
    )
    match_key: Mapped[str | None] = mapped_column(
        String, index=True,
        comment='同类项聚合键（M1.2 compute：优先级 dict > std > Z前缀 > 有效国标码 > raw，带清单版本维度）',
    )
    aggregate_id: Mapped[str | None] = mapped_column(
        String, index=True,
        comment='跨行聚合身份（material_dict_id 存在时 = dict:<id>，否则 = match_key。'
                'M3 单价分析 / M4 成本库迁移一律按此字段聚合）',
    )
    match_key_source: Mapped[str | None] = mapped_column(
        String(20),
        comment='聚合键来源（dict/std/code/raw），让统计口径可解释',
    )
    anomaly_flag: Mapped[str] = mapped_column(
        String(20), default='normal', index=True,
        comment='异常标记（normal/warning/error，B 类）',
    )
    anomaly_reason: Mapped[str | None] = mapped_column(Text, comment='异常原因（B 类）')

    # ------------------------------------------------------------------
    # 软删除 / 孤儿（M1 §4.9 状态语义）
    # ------------------------------------------------------------------
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, comment='有效（软删除标记）')
    orphaned: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment='孤儿行（仅由重导产生：active=False + orphaned=True 进待确认/回收站，与 anomaly_flag 正交）',
    )

    # ------------------------------------------------------------------
    # 溯源补充 / 系统
    # ------------------------------------------------------------------
    source_path: Mapped[str | None] = mapped_column(String, comment='来源路径（仅人读参考，正式溯源走批次 archive_path）')
    source_sheet: Mapped[str | None] = mapped_column(String, comment='来源 Sheet')
    classification: Mapped[dict | None] = mapped_column(JSON, comment='编码解析（专业/分部）')
    extra: Mapped[dict | None] = mapped_column(JSON, comment='未映射列（原样保留）')
    version: Mapped[int] = mapped_column(Integer, default=1, comment='版本')

    # ------------------------------------------------------------------
    # 关系（SQLAlchemy relationship，不建额外列）
    # ------------------------------------------------------------------
    import_batch = relationship("ImportBatch", back_populates="item_ids", foreign_keys=[import_batch_id])
    material_dict = relationship("MaterialDict", foreign_keys=[material_dict_id])
    parent = relationship("BoqItem", remote_side=[id], foreign_keys=[parent_id])
    child_ids = relationship("BoqItem", back_populates="parent", foreign_keys=[parent_id])

    # ------------------------------------------------------------------
    # 声明式索引（M1 §4.5）
    # ------------------------------------------------------------------
    __table_args__ = (
        Index("ix_boq_item_code_unit", "item_code", "unit"),
        Index("ix_boq_item_project_seq", "project_name", "sequence"),
        Index("ix_boq_item_province_period", "province", "price_period"),
        Index("ix_boq_item_batch_seq", "import_batch_id", "sequence"),
    )

    def __repr__(self):
        return f"<BoqItem id={self.id} biz_id={self.biz_id} item_name={self.item_name!r}>"
