# -*- coding: utf-8 -*-
"""M1.3 分层 Upsert 与孤儿测试（S3/S4 安全用例语义）。

S3：A 类字段可覆盖（重导时更新）
S4：B 类字段禁静默覆盖（已有值保留，孤儿可还原）

运行：
    python.exe -m pytest tests/test_upsert.py -v
"""
import pytest
from app.models import BoqItem, ImportBatch
from app.services.upsert_service import upsert_rows, preview_upsert


class TestUpsertCreate:
    """全新批次导入：全部 created。"""

    def test_new_batch_all_created(self, db_session):
        """全新批次（无已有行）→ 全部 created。"""
        batch = ImportBatch(name="新批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        rows = [
            {"sequence": 1, "item_name": "电缆", "item_code": "030408001", "quantity": "100"},
            {"sequence": 2, "item_name": "钢管", "item_code": "030701001", "quantity": "50"},
        ]
        stats = upsert_rows(db_session, batch.id, rows, operator="tester")

        assert stats["created"] == 2
        assert stats["updated"] == 0
        assert stats["orphaned"] == 0
        assert stats["preserved_manual"] == 0

        # 验证数据落库
        items = db_session.query(BoqItem).filter(BoqItem.import_batch_id == batch.id).all()
        assert len(items) == 2
        assert items[0].item_name == "电缆"
        assert items[0].data_source_type == "completed"  # B_DEFAULTS 兜底


class TestUpsertUpdateAFields:
    """S3：A 类字段可覆盖。"""

    def test_a_field_updated_on_reimport(self, db_session):
        """重导时 A 类字段（quantity/unit_rate 等）被覆盖更新。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        # 首次导入
        rows1 = [{"sequence": 1, "item_name": "电缆", "quantity": "100", "unit_rate": "50"}]
        upsert_rows(db_session, batch.id, rows1)
        db_session.flush()

        item = db_session.query(BoqItem).filter_by(import_batch_id=batch.id, sequence=1).first()
        assert item.quantity == "100"
        assert item.unit_rate == "50"

        # 重导：A 类字段变化
        rows2 = [{"sequence": 1, "item_name": "电缆", "quantity": "200", "unit_rate": "55"}]
        stats = upsert_rows(db_session, batch.id, rows2)

        assert stats["updated"] == 1
        assert stats["created"] == 0

        # A 类字段被覆盖
        db_session.refresh(item)
        assert item.quantity == "200"
        assert item.unit_rate == "55"


class TestUpsertPreserveBFields:
    """S4：B 类字段禁静默覆盖（已有值保留）。"""

    def test_b_field_preserved_on_reimport(self, db_session):
        """重导时 B 类字段（std_name/std_spec 等）已有值不被覆盖。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        # 首次导入（含 B 类标注）
        rows1 = [{
            "sequence": 1, "item_name": "电缆",
            "std_name": "电力电缆", "std_spec": "YJV-3x120",
            "anomaly_flag": "normal",
        }]
        upsert_rows(db_session, batch.id, rows1)
        db_session.flush()

        item = db_session.query(BoqItem).filter_by(import_batch_id=batch.id, sequence=1).first()
        assert item.std_name == "电力电缆"
        assert item.std_spec == "YJV-3x120"

        # 重导：B 类字段传入不同值（模拟 Excel 无标注或不同标注）
        rows2 = [{
            "sequence": 1, "item_name": "电缆",
            "std_name": "错误标注", "std_spec": "错误规格",
            "quantity": "100",
        }]
        upsert_rows(db_session, batch.id, rows2)

        # B 类字段保留原值，不被覆盖
        db_session.refresh(item)
        assert item.std_name == "电力电缆"  # 保留
        assert item.std_spec == "YJV-3x120"  # 保留
        # A 类字段被更新
        assert item.quantity == "100"

    def test_b_field_empty_filled_on_reimport(self, db_session):
        """B 类字段为空时，重导可填入（仅空时写入）。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        # 首次导入（无 B 类标注）
        rows1 = [{"sequence": 1, "item_name": "电缆", "quantity": "100"}]
        upsert_rows(db_session, batch.id, rows1)
        db_session.flush()

        item = db_session.query(BoqItem).filter_by(import_batch_id=batch.id, sequence=1).first()
        assert item.std_name is None  # 空

        # 重导：填入 B 类标注
        rows2 = [{"sequence": 1, "item_name": "电缆", "std_name": "电力电缆", "std_spec": "YJV"}]
        upsert_rows(db_session, batch.id, rows2)

        # B 类字段被填入（原为空）
        db_session.refresh(item)
        assert item.std_name == "电力电缆"
        assert item.std_spec == "YJV"


class TestUpsertOrphan:
    """孤儿行检测与软标记（不物理删除）。"""

    def test_orphan_rows_soft_marked(self, db_session):
        """原批次有、新导入无的行 → active=False + orphaned=True，不物理删除。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        # 首次导入 3 行
        rows1 = [
            {"sequence": 1, "item_name": "电缆"},
            {"sequence": 2, "item_name": "钢管"},
            {"sequence": 3, "item_name": "桥架"},
        ]
        upsert_rows(db_session, batch.id, rows1)
        db_session.flush()

        # 重导：只保留前 2 行，第 3 行变为孤儿
        rows2 = [
            {"sequence": 1, "item_name": "电缆"},
            {"sequence": 2, "item_name": "钢管"},
        ]
        stats = upsert_rows(db_session, batch.id, rows2)

        assert stats["orphaned"] == 1
        assert stats["updated"] == 2
        assert stats["created"] == 0

        # 孤儿行仍在库中（软标记，不物理删除）
        orphan = db_session.query(BoqItem).filter_by(import_batch_id=batch.id, sequence=3).first()
        assert orphan is not None  # 仍在
        assert orphan.active is False
        assert orphan.orphaned is True

    def test_orphan_row_restorable(self, db_session):
        """孤儿行可还原（active=True + orphaned=False）。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        rows1 = [{"sequence": 1, "item_name": "电缆"}, {"sequence": 2, "item_name": "钢管"}]
        upsert_rows(db_session, batch.id, rows1)
        db_session.flush()

        rows2 = [{"sequence": 1, "item_name": "电缆"}]
        upsert_rows(db_session, batch.id, rows2)
        db_session.flush()

        # 还原孤儿行
        orphan = db_session.query(BoqItem).filter_by(import_batch_id=batch.id, sequence=2).first()
        assert orphan.active is False
        orphan.active = True
        orphan.orphaned = False
        db_session.flush()

        # 还原后正常
        db_session.refresh(orphan)
        assert orphan.active is True
        assert orphan.orphaned is False


class TestUpsertOrphanBackfill:
    """孤儿 B 类回灌（v6.5 P0-3）。"""

    def test_orphan_b_fields_backfill_to_new_row(self, db_session):
        """孤儿行（含 B 类标注）与新建行同 material_dict_id → B 类回灌到新建行。"""
        from app.models import MaterialDict
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        # 建物料字典
        l1 = MaterialDict(level="l1", name="电气")
        db_session.add(l1)
        db_session.flush()
        l3 = MaterialDict(level="l3", name="YJV", parent_id=l1.id)
        db_session.add(l3)
        db_session.flush()

        # 首次导入：含 B 类标注 + material_dict_id
        rows1 = [{
            "sequence": 1, "item_name": "电缆",
            "std_name": "电力电缆", "std_spec": "YJV-3x120",
            "material_dict_id": l3.id,
        }]
        upsert_rows(db_session, batch.id, rows1)
        db_session.flush()

        # 重导：sequence 变化（原 seq=1 变孤儿，新 seq=10 新建），候选键不同但同 material_dict_id
        rows2 = [{
            "sequence": 10, "item_name": "电缆敷设",  # 候选键不同 → 新建行
            "material_dict_id": l3.id,  # 同物料字典 → 回灌命中
        }]
        stats = upsert_rows(db_session, batch.id, rows2)

        assert stats["orphaned"] == 1
        assert stats["created"] == 1
        assert stats["preserved_manual"] >= 1  # B 类回灌

        # 新建行获得了孤儿的 B 类标注
        new_item = db_session.query(BoqItem).filter_by(import_batch_id=batch.id, sequence=10).first()
        assert new_item.std_name == "电力电缆"  # 回灌
        assert new_item.std_spec == "YJV-3x120"  # 回灌


class TestUpsertCandidateKey:
    """候选键兜底匹配（行序调整场景）。"""

    def test_candidate_key_match_when_sequence_changes(self, db_session):
        """行序变化时，按候选键 (item_code, item_name, unit_std) 兜底匹配。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        # 首次导入：seq=1
        rows1 = [{"sequence": 1, "item_name": "电缆", "item_code": "030408001", "unit_std": "m", "quantity": "100"}]
        upsert_rows(db_session, batch.id, rows1)
        db_session.flush()

        item_id = db_session.query(BoqItem).filter_by(import_batch_id=batch.id).first().id

        # 重导：seq 变为 5（行序调整），但候选键相同 → 应匹配到已有行（updated），不是新建
        rows2 = [{"sequence": 5, "item_name": "电缆", "item_code": "030408001", "unit_std": "m", "quantity": "200"}]
        stats = upsert_rows(db_session, batch.id, rows2)

        assert stats["updated"] == 1  # 候选键匹配到已有行
        assert stats["created"] == 0

        # 原行被更新（sequence 变为 5）
        item = db_session.get(BoqItem, item_id)
        assert item.sequence == 5
        assert item.quantity == "200"


class TestPreviewUpsert:
    """预览模式：只计算不写库。"""

    def test_preview_does_not_write(self, db_session):
        """预览模式不写库，返回统计信封。"""
        batch = ImportBatch(name="批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()

        rows = [
            {"sequence": 1, "item_name": "电缆"},
            {"sequence": 2, "item_name": "钢管"},
        ]
        stats = preview_upsert(db_session, batch.id, rows)

        assert stats["created"] == 2
        assert stats["updated"] == 0
        assert stats["orphaned"] == 0

        # 验证未写库
        count = db_session.query(BoqItem).filter(BoqItem.import_batch_id == batch.id).count()
        assert count == 0
