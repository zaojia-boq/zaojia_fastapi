# -*- coding: utf-8 -*-
"""import_batch —— 导入批次（M1 §4.2 / §4.10 / §16.1 落地，SQLAlchemy 版）。

设计来源：原 Odoo 版 zaojia.import.batch。
- file_hash = SHA256，幂等键；
- active 软删除；checksum_* 三项在导入完成后固化（M1 §4.10）；
- 批次级 data_source_type 有默认值 completed（行级模型强制 required）。
"""
from datetime import date, datetime

from sqlalchemy import String, Integer, Boolean, Date, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_mixin import Base, BizIdMixin, TimestampMixin


class ImportBatch(Base, BizIdMixin, TimestampMixin):
    """导入批次。"""
    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str | None] = mapped_column(String, comment='批次名（默认：源文件名 + 时间戳）')
    source_file: Mapped[str | None] = mapped_column(String, comment='来源文件名')
    file_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, comment='文件校验和 SHA256（幂等键）',
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0, comment='解析总行数')
    imported_count: Mapped[int] = mapped_column(Integer, default=0, comment='入库行数')
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, comment='跳过行数')
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0, comment='异常行数')
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, comment='入库时间',
    )
    province: Mapped[str | None] = mapped_column(String, comment='地区（批次级，行级可覆盖）')
    price_period: Mapped[date | None] = mapped_column(
        Date, comment='价格期（批次级，行级可覆盖，存当月 1 日）',
    )
    operator: Mapped[str | None] = mapped_column(
        String, comment='操作人（OA 用户名，用户删除不连带批次）',
    )
    archive_path: Mapped[str | None] = mapped_column(
        String, comment='归档相对路径（为空即归档失败，属异常批次）',
    )
    source_path: Mapped[str | None] = mapped_column(
        String, comment='原始路径（仅供人读参考，文件可能已被移动）',
    )
    checksum_count: Mapped[int | None] = mapped_column(
        Integer, comment='校验行数（入库行数校验，仅数 active=True）',
    )
    checksum_total: Mapped[float | None] = mapped_column(
        Numeric(16, 2), comment='校验合价（sum(total_num)，Decimal 累加后取 2 位）',
    )
    checksum_hash: Mapped[str | None] = mapped_column(
        String(64), comment='校验哈希（按 sequence 升序拼接关键字段后 SHA256）',
    )
    data_source_type: Mapped[str] = mapped_column(
        String(20), default='completed',
        comment='数据性质（批次级，行级可覆盖。行级模型强制 required）',
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, comment='有效（软删除标记）')
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment='软删除时间（进入回收站的时间，30 天硬删窗口起点）',
    )

    # 关系
    item_ids = relationship("BoqItem", back_populates="import_batch", foreign_keys="BoqItem.import_batch_id")

    def __repr__(self):
        return f"<ImportBatch id={self.id} name={self.name!r}>"
