# -*- coding: utf-8 -*-
"""SQLAlchemy 四核心模型测试（M1.1）。

覆盖：
- BoqItem：创建/字段/biz_id 自动生成/data_source_type 必填/软删/外键关系
- ImportBatch：创建/校验和字段/软删
- MaterialDict：三级树创建/自引用关系
- AuditLog：append-only（update/delete 拒绝）

运行：
    python.exe -m pytest tests/test_models.py -v
"""
import pytest
from decimal import Decimal
from datetime import date

from app.models import BoqItem, ImportBatch, MaterialDict, AuditLog


class TestBoqItem:
    """清单项模型测试。"""

    def test_create_basic(self, db_session):
        """基础创建：必填字段 + biz_id 自动生成。"""
        batch = ImportBatch(name="测试批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        item = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆敷设",
            item_code="030408001001",
            unit="m",
            quantity="100",
            quantity_num=Decimal("100.000000"),
            unit_rate="50.5",
            unit_rate_num=Decimal("50.500000"),
            total="5050",
            total_num=Decimal("5050.000000"),
            data_source_type="completed",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        assert item.id is not None
        assert item.biz_id is not None
        assert len(item.biz_id) == 36  # UUID4 格式
        assert item.item_name == "电缆敷设"
        assert item.active is True
        assert item.orphaned is False
        assert item.anomaly_flag == "normal"

    def test_biz_id_auto_generated(self, db_session):
        """biz_id 未显式传入时自动生成 UUID4。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        item = BoqItem(
            import_batch_id=batch.id,
            item_name="测试项",
            data_source_type="completed",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        assert item.biz_id is not None
        # UUID4 格式：8-4-4-4-12
        parts = item.biz_id.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]

    def test_data_source_type_required(self, db_session):
        """data_source_type 必填（nullable=False），不传应报错。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        item = BoqItem(
            import_batch_id=batch.id,
            item_name="测试项",
            # 不传 data_source_type
            sequence=1,
        )
        db_session.add(item)
        with pytest.raises(Exception):
            db_session.flush()  # NOT NULL 约束违反

    def test_soft_delete(self, db_session):
        """软删除：active=False + orphaned=True，记录仍在库中。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        item = BoqItem(
            import_batch_id=batch.id,
            item_name="待删项",
            data_source_type="completed",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()
        item_id = item.id

        # 软删
        item.active = False
        item.orphaned = True
        db_session.flush()

        # 记录仍在
        found = db_session.get(BoqItem, item_id)
        assert found is not None
        assert found.active is False
        assert found.orphaned is True

    def test_relationship_import_batch(self, db_session):
        """外键关系：boq_item.import_batch → import_batch.item_ids。"""
        batch = ImportBatch(name="关联批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        item1 = BoqItem(
            import_batch_id=batch.id,
            item_name="项1",
            data_source_type="completed",
            sequence=1,
        )
        item2 = BoqItem(
            import_batch_id=batch.id,
            item_name="项2",
            data_source_type="completed",
            sequence=2,
        )
        db_session.add_all([item1, item2])
        db_session.flush()

        assert item1.import_batch.id == batch.id
        assert len(batch.item_ids) == 2

    def test_price_period_stores_first_of_month(self, db_session):
        """价格期存储约定：存当月 1 日。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        item = BoqItem(
            import_batch_id=batch.id,
            item_name="价格期测试",
            data_source_type="completed",
            price_period=date(2026, 3, 1),
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        assert item.price_period == date(2026, 3, 1)
        assert item.price_period.day == 1


class TestImportBatch:
    """导入批次模型测试。"""

    def test_create_basic(self, db_session):
        """基础创建。"""
        batch = ImportBatch(
            name="2026-03 沈阳项目",
            source_file="沈阳项目清单.xlsx",
            file_hash="a" * 64,
            row_count=100,
            imported_count=95,
            skipped_count=5,
            data_source_type="completed",
            province="辽宁",
        )
        db_session.add(batch)
        db_session.flush()

        assert batch.id is not None
        assert batch.biz_id is not None
        assert batch.active is True
        assert batch.imported_count == 95

    def test_soft_delete_with_deleted_at(self, db_session):
        """软删除：active=False + deleted_at 记录时间。"""
        from datetime import datetime
        batch = ImportBatch(name="待删批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()
        batch_id = batch.id

        batch.active = False
        batch.deleted_at = datetime.utcnow()
        db_session.flush()

        found = db_session.get(ImportBatch, batch_id)
        assert found.active is False
        assert found.deleted_at is not None


class TestMaterialDict:
    """物料分类字典模型测试。"""

    def test_create_three_level_tree(self, db_session):
        """三级树创建：大类→系列→规格集合。"""
        l1 = MaterialDict(level="l1", name="电气设备")
        db_session.add(l1)
        db_session.flush()

        l2 = MaterialDict(level="l2", name="电缆", parent_id=l1.id)
        db_session.add(l2)
        db_session.flush()

        l3 = MaterialDict(
            level="l3",
            name="YJV 电力电缆",
            parent_id=l2.id,
            synonyms=["电力电缆", "YJV电缆"],
            spec_whitelist=["3x120+1x70", "4x95"],
        )
        db_session.add(l3)
        db_session.flush()

        assert l3.parent.id == l2.id
        assert l2.parent.id == l1.id
        assert len(l1.child_ids) == 1
        assert l3.synonyms == ["电力电缆", "YJV电缆"]

    def test_boq_item_links_material_dict(self, db_session):
        """清单项关联物料字典（B 类字段）。"""
        l1 = MaterialDict(level="l1", name="电气")
        db_session.add(l1)
        db_session.flush()
        l3 = MaterialDict(level="l3", name="YJV", parent_id=l1.id)
        db_session.add(l3)
        db_session.flush()

        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        item = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆",
            data_source_type="completed",
            material_dict_id=l3.id,
            std_name="电力电缆",
            std_spec="YJV-3x120",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        assert item.material_dict.id == l3.id
        assert item.std_name == "电力电缆"  # B 类字段


class TestAuditLog:
    """审计日志模型测试（append-only）。"""

    def test_create_log(self, db_session):
        """创建审计日志（允许）。"""
        log = AuditLog(
            model="boq_item",
            res_id=1,
            action="create",
            operator="test_user",
            reason="测试导入",
            trace_id="trace-001",
        )
        db_session.add(log)
        db_session.flush()

        assert log.id is not None
        assert log.timestamp is not None

    def test_update_rejected(self, db_session):
        """append-only：修改审计日志应被拒绝。"""
        log = AuditLog(model="boq_item", res_id=1, action="create", operator="u1")
        db_session.add(log)
        db_session.flush()

        log.reason = "试图修改"
        with pytest.raises(PermissionError, match="append-only"):
            db_session.flush()

    def test_delete_rejected(self, db_session):
        """append-only：删除审计日志应被拒绝。"""
        from tests.conftest import TestingSessionLocal

        log = AuditLog(model="boq_item", res_id=1, action="create", operator="u1")
        db_session.add(log)
        db_session.commit()  # 先提交，确保记录持久化
        log_id = log.id

        # 用新 session 做删除测试（避免 rollback 撤销 insert）
        session2 = TestingSessionLocal()
        try:
            log2 = session2.get(AuditLog, log_id)
            assert log2 is not None
            session2.delete(log2)
            with pytest.raises(PermissionError, match="append-only"):
                session2.flush()
        finally:
            session2.rollback()
            session2.close()

        # 原 session 重新查询，记录仍在
        db_session.expire_all()
        assert db_session.get(AuditLog, log_id) is not None
