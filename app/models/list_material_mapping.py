# -*- coding: utf-8 -*-
"""list_material_mapping —— GB50500清单项目与中建材料字典映射表。

支持 GB50500-2013 和 GBT50500-2024 两个版本，通过 list_version 字段区分。
存储清单项目编码/名称与材料字典编码/名称的匹配映射关系，
用于单价分析时快速定位清单项目对应的材料。
"""
from sqlalchemy import String, Integer, Float, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_mixin import Base, BizIdMixin, TimestampMixin


class ListMaterialMapping(Base, BizIdMixin, TimestampMixin):
    """清单项目-材料字典映射表（支持2013/2024双版本）。"""
    __tablename__ = "list_material_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    list_version: Mapped[str] = mapped_column(
        String(8), nullable=False, index=True, default='2024',
        comment='清单规范版本（2013 / 2024）',
    )
    list_item_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment='清单项目编码（9位）',
    )
    list_item_name: Mapped[str] = mapped_column(
        String, nullable=False, index=True,
        comment='清单项目名称',
    )
    material_code: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment='材料字典编码（中建材料字典，15位含前缀I）',
    )
    material_name: Mapped[str] = mapped_column(
        String, nullable=False, index=True,
        comment='材料名称',
    )
    match_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment='匹配类型（exact_name精确/fuzzy_name模糊/feature_match项目特征匹配）',
    )
    similarity: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment='相似度（0-100）',
    )

    __table_args__ = (
        Index('ix_list_material_mapping_version_code', 'list_version', 'list_item_code'),
    )

    def __repr__(self):
        return f"<ListMaterialMapping id={self.id} v={self.list_version} list={self.list_item_code} material={self.material_code}>"
