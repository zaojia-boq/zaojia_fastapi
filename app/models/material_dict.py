# -*- coding: utf-8 -*-
"""material_dict —— 三级材料分类字典（架构 §7.3 / M1 §4.6 落地，SQLAlchemy 版）。

设计来源：原 Odoo 版 zaojia.material.dict。
- 小表（预计 < 1000 行）、读多写少；
- cat_l1/l2/l3 为冗余平铺（避免递归检索）；
- synonyms（业务同义词）/ spec_whitelist（规格白名单）为 JSON；
- 职责边界：表头别名在 aliases.py，单位归一在 unit_normalize.py，三者不混。
"""
from sqlalchemy import String, Text, Integer, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_mixin import Base, BizIdMixin, TimestampMixin


class MaterialDict(Base, BizIdMixin, TimestampMixin):
    """物料分类字典（三级树：大类→系列→规格集合）。"""
    __tablename__ = "material_dict"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    level: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment='层级（l1 大类 / l2 系列 / l3 规格集合）',
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_dict.id", ondelete="RESTRICT"),
        nullable=True, index=True,
        comment='父级（树形三级。有子级/被引用时禁止删除，须先删叶子）',
    )
    name: Mapped[str] = mapped_column(String, nullable=False, index=True, comment='名称（L3 为规格集合名）')
    cat_l1: Mapped[str | None] = mapped_column(String, comment='一级分类（冗余平铺，由父链自动写入）')
    cat_l2: Mapped[str | None] = mapped_column(String, comment='二级分类（冗余平铺，由父链自动写入）')
    cat_l3: Mapped[str | None] = mapped_column(String, comment='三级分类（冗余平铺，由父链自动写入）')
    synonyms: Mapped[dict | None] = mapped_column(
        JSON, comment='同义词（物料业务同义词，如 电缆/电力电缆/YJV）',
    )
    spec_whitelist: Mapped[dict | None] = mapped_column(
        JSON, comment='规格白名单（合法规格取值集合，用于归一/校验）',
    )
    note: Mapped[str | None] = mapped_column(Text, comment='备注')

    # 关系（自引用树）
    parent = relationship("MaterialDict", remote_side=[id], foreign_keys=[parent_id])
    child_ids = relationship("MaterialDict", back_populates="parent", foreign_keys=[parent_id])

    def __repr__(self):
        return f"<MaterialDict id={self.id} level={self.level} name={self.name!r}>"
