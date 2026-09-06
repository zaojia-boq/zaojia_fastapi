# -*- coding: utf-8 -*-
"""M1.2 编码解析与 match_key 自动计算测试。

三判据实证（M1模块设计.md §4.7②）：
1. 同码 2013/2024 分键（F1 版本维度）
2. 截位（12 位编码 → 前 9 位匹配）
3. Z 前缀（强制 2024，F3）

运行：
    python.exe -m pytest tests/test_match_key.py -v
"""
import pytest
from app.models import BoqItem, ImportBatch


class TestMatchKeyAutoCompute:
    """match_key 自动计算（before_insert 事件）。"""

    def _make_batch(self, db_session):
        batch = ImportBatch(name="测试批次", data_source_type="completed")
        db_session.add(batch)
        db_session.flush()
        return batch

    def test_basic_insert_auto_computes_match_key(self, db_session):
        """基础 insert：match_key / match_key_source / aggregate_id 自动计算。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆敷设",
            item_code="030408001",
            unit="m",
            unit_std="m",
            data_source_type="completed",
            item_code_version="2013",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        assert item.match_key is not None
        assert item.match_key_source == "code"
        assert item.aggregate_id is not None
        # 有效国标码 → code:{ver}:{code_9}|{unit_std}
        assert item.match_key.startswith("code:2013:030408001|")

    def test_f1_version_dimension_2013_vs_2024(self, db_session):
        """判据1（F1）：同码 2013/2024 生成不同 match_key，不跨版本误聚合。"""
        batch = self._make_batch(db_session)

        item_2013 = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆",
            item_code="030408001",
            unit_std="m",
            data_source_type="completed",
            item_code_version="2013",
            sequence=1,
        )
        item_2024 = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆",
            item_code="030408001",
            unit_std="m",
            data_source_type="completed",
            item_code_version="2024",
            sequence=2,
        )
        db_session.add_all([item_2013, item_2024])
        db_session.flush()

        # 同码不同版本 → 不同 match_key
        assert item_2013.match_key != item_2024.match_key
        assert "2013" in item_2013.match_key
        assert "2024" in item_2024.match_key

    def test_f2_12digit_truncation(self, db_session):
        """判据2（截位）：12 位编码 → 前 9 位用于匹配，完整值保留在 item_code。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="测试项",
            item_code="030408001001",  # 12 位
            unit_std="m",
            data_source_type="completed",
            item_code_version="2013",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        # item_code 保留完整 12 位
        assert item.item_code == "030408001001"
        # match_key 用前 9 位
        assert "030408001" in item.match_key
        assert item.match_key_source == "code"

    def test_f3_z_prefix_forces_2024(self, db_session):
        """判据3（F3）：Z 前缀编码强制 2024 版本，即使 item_code_version=2013。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="总图工程",
            item_code="Z01001",
            unit_std="项",
            data_source_type="completed",
            item_code_version="2013",  # 故意设 2013
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        # Z 前缀强制 2024
        assert item.match_key.startswith("code:2024:Z01001|")
        assert item.match_key_source == "code"

    def test_dict_priority_highest(self, db_session):
        """物料字典（B 类人工标注）优先级最高 → match_key_source=dict。"""
        from app.models import MaterialDict
        batch = self._make_batch(db_session)

        l1 = MaterialDict(level="l1", name="电气")
        db_session.add(l1)
        db_session.flush()
        l3 = MaterialDict(level="l3", name="YJV电缆", parent_id=l1.id)
        db_session.add(l3)
        db_session.flush()

        item = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆",
            item_code="030408001",
            unit_std="m",
            std_name="电力电缆",
            std_spec="YJV",
            material_dict_id=l3.id,
            data_source_type="completed",
            item_code_version="2013",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        # 有物料字典 → dict 优先级最高
        assert item.match_key_source == "dict"
        assert item.match_key.startswith(f"dict:{l3.id}|")
        # aggregate_id = dict:<id>
        assert item.aggregate_id == f"dict:{l3.id}"

    def test_std_priority_above_code(self, db_session):
        """标准化名称+规格（B 类）优先级高于编码。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆",
            item_code="030408001",
            unit_std="m",
            std_name="电力电缆",
            std_spec="YJV-3x120",
            data_source_type="completed",
            item_code_version="2013",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        assert item.match_key_source == "std"
        assert item.match_key.startswith("std:电力电缆|YJV-3x120|")

    def test_raw_fallback(self, db_session):
        """无字典/无标准化/无有效编码 → raw 兜底（带版本维度）。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="自定义项",
            item_code="ABC123",  # 非国标码
            unit_std="个",
            data_source_type="completed",
            item_code_version="unknown",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        assert item.match_key_source == "raw"
        assert item.match_key.startswith("raw:unknown:")

    def test_item_code_normalization_on_insert(self, db_session):
        """insert 时 item_code 自动规范化，原始值保留在 item_code_raw。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="测试项",
            item_code="030408001001",  # 12 位
            data_source_type="completed",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        # item_code_raw 保留原始输入
        assert item.item_code_raw == "030408001001"
        # item_code 规范化后仍为 12 位（parse_gb_code code_full = 原值）
        assert item.item_code == "030408001001"

    def test_update_recomputes_when_dependency_changes(self, db_session):
        """update 时：std_name 变化 → match_key 重新计算（从 code 升级为 std）。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆",
            item_code="030408001",
            unit_std="m",
            data_source_type="completed",
            item_code_version="2013",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        # 初始：无标准化 → code
        assert item.match_key_source == "code"
        old_key = item.match_key

        # 更新：添加标准化名称+规格 → 升级为 std
        item.std_name = "电力电缆"
        item.std_spec = "YJV-3x120"
        db_session.flush()

        assert item.match_key_source == "std"
        assert item.match_key != old_key
        assert item.match_key.startswith("std:电力电缆|YJV-3x120|")

    def test_update_no_recompute_when_unrelated_field_changes(self, db_session):
        """update 时：非依赖字段（如 quantity）变化 → match_key 不重新计算。"""
        batch = self._make_batch(db_session)
        item = BoqItem(
            import_batch_id=batch.id,
            item_name="电缆",
            item_code="030408001",
            unit_std="m",
            data_source_type="completed",
            item_code_version="2013",
            sequence=1,
        )
        db_session.add(item)
        db_session.flush()

        old_key = item.match_key
        old_source = item.match_key_source

        # 修改非依赖字段
        item.quantity = "200"
        db_session.flush()

        # match_key 不变
        assert item.match_key == old_key
        assert item.match_key_source == old_source
