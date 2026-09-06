# -*- coding: utf-8 -*-
"""M4 成本库 + 迁移服务测试。

注意：BoqItem 的 match_key 由 before_insert 事件监听器自动计算（基于 item_code 等），
测试中不手动设置 match_key，而是创建后从 DB 读取实际值。
同一 item_code 的多条记录归入同一 match_key（同一聚合组）。
"""
import pytest
from datetime import date

from app.models.boq_item import BoqItem
from app.models.import_batch import ImportBatch
from app.models.cost_catalog import CostCatalog
from app.services import cost_migration_service

DEV_TOKEN = "zaojia-dev-token-2026"
AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}


def _make_batch(db, name="test-batch"):
    batch = ImportBatch(
        name=name, source_file=f"{name}.xlsx", file_hash="h1",
        row_count=5, imported_count=5, skipped_count=0, anomaly_count=0,
        data_source_type="completed", operator="tester",
    )
    db.add(batch)
    db.flush()
    return batch


def _make_item(db, batch_id, **kwargs):
    """创建 boq_item。match_key 由事件自动计算，创建后刷新获取。"""
    defaults = {
        'item_code': '030404001001',
        'item_name': '测试项', 'item_feature': '测试特征',
        'unit': 'm', 'quantity_num': 100, 'unit_rate': '50.00', 'unit_rate_num': 50.0,
        'total_num': 5000.0,
        'data_source_type': 'completed', 'province': '辽宁',
        'price_period': date(2026, 3, 1), 'active': True,
        'anomaly_flag': 'normal',
    }
    if 'unit_rate' in kwargs and 'unit_rate_num' not in kwargs:
        kwargs['unit_rate_num'] = kwargs['unit_rate']
        kwargs['unit_rate'] = str(kwargs['unit_rate'])
    kwargs.pop('match_key', None)
    kwargs.pop('match_key_source', None)
    defaults.update(kwargs)
    item = BoqItem(import_batch_id=batch_id, **defaults)
    db.add(item)
    db.flush()
    db.refresh(item)
    return item


def _mk_of(db, item):
    """获取 item 的实际 match_key。"""
    return db.query(BoqItem.match_key).filter(BoqItem.id == item.id).scalar()


# ============================================================================
# 模型层测试
# ============================================================================

class TestCostCatalogModel:
    def test_create_cost_catalog(self, db_session):
        record = CostCatalog(
            match_key="code:030404001001", match_key_source="code",
            std_name="测试项", std_spec="测试规格", unit_std="m",
            avg_rate=100.0, min_rate=90.0, max_rate=110.0, sample_count=3,
        )
        db_session.add(record)
        db_session.commit()
        fetched = db_session.query(CostCatalog).filter_by(match_key="code:030404001001").first()
        assert fetched is not None
        assert fetched.std_name == "测试项"
        assert float(fetched.avg_rate) == 100.0

    def test_match_key_unique(self, db_session):
        r1 = CostCatalog(match_key="unique:key", std_name="A", unit_std="m")
        db_session.add(r1)
        db_session.commit()
        r2 = CostCatalog(match_key="unique:key", std_name="B", unit_std="m")
        db_session.add(r2)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()

    def test_soft_delete(self, db_session):
        record = CostCatalog(match_key="soft:key", std_name="A", unit_std="m", active=True)
        db_session.add(record)
        db_session.commit()
        record.active = False
        db_session.commit()
        active = db_session.query(CostCatalog).filter(
            CostCatalog.match_key == "soft:key", CostCatalog.active == True).first()
        assert active is None


# ============================================================================
# 迁移聚合测试
# ============================================================================

class TestMigrationAggregation:
    def test_aggregate_basic(self, db_session):
        """3 条同 item_code，单价 100/110/120 → avg=110。"""
        batch = _make_batch(db_session)
        items = []
        for i, rate in enumerate([100, 110, 120]):
            items.append(_make_item(db_session, batch.id, unit_rate=rate,
                                    price_period=date(2026, 1+i, 1)))
        db_session.commit()
        mk = _mk_of(db_session, items[0])
        agg = cost_migration_service._aggregate_for_match_key(db_session, mk)
        assert agg is not None
        assert agg['sample_count'] == 3
        assert agg['avg_rate'] == pytest.approx(110.0, abs=0.01)
        assert agg['min_rate'] == 100
        assert agg['max_rate'] == 120

    def test_aggregate_skip_empty_rate(self, db_session):
        """空单价行排除。"""
        batch = _make_batch(db_session)
        i1 = _make_item(db_session, batch.id, unit_rate=100)
        _make_item(db_session, batch.id, unit_rate=120)
        _make_item(db_session, batch.id, unit_rate=None, unit_rate_num=None)
        db_session.commit()
        mk = _mk_of(db_session, i1)
        agg = cost_migration_service._aggregate_for_match_key(db_session, mk)
        assert agg['sample_count'] == 2
        assert agg['avg_rate'] == 110.0

    def test_aggregate_skip_non_completed(self, db_session):
        """非 completed 行排除。"""
        batch = _make_batch(db_session)
        i1 = _make_item(db_session, batch.id, unit_rate=100, data_source_type='completed')
        _make_item(db_session, batch.id, unit_rate=200, data_source_type='pending_review')
        db_session.commit()
        mk = _mk_of(db_session, i1)
        agg = cost_migration_service._aggregate_for_match_key(db_session, mk)
        assert agg['sample_count'] == 1
        assert agg['avg_rate'] == 100.0

    def test_aggregate_no_data_returns_none(self, db_session):
        agg = cost_migration_service._aggregate_for_match_key(db_session, 'nonexistent:key')
        assert agg is None

    def test_aggregate_latest_by_period(self, db_session):
        """最新记录按 price_period 降序。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100, price_period=date(2025, 1, 1),
                   item_name='旧名称')
        i2 = _make_item(db_session, batch.id, unit_rate=120, price_period=date(2026, 6, 1),
                        item_name='新名称')
        db_session.commit()
        mk = _mk_of(db_session, i2)
        agg = cost_migration_service._aggregate_for_match_key(db_session, mk)
        assert agg['std_name'] == '新名称'
        assert agg['latest_price'] == 120.0


# ============================================================================
# 迁移预览测试
# ============================================================================

class TestMigrationPreview:
    def test_preview_empty(self, db_session):
        result = cost_migration_service.preview_migration(db_session)
        assert result['will_migrate'] == 0

    def test_preview_with_data(self, db_session):
        """2 个不同 item_code → 2 个 match_key。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100, item_code='030404001001')
        _make_item(db_session, batch.id, unit_rate=110, item_code='030404001001')
        _make_item(db_session, batch.id, unit_rate=200, item_code='030404002001')
        db_session.commit()
        result = cost_migration_service.preview_migration(db_session)
        assert result['will_migrate'] == 2
        assert result['total_match_keys'] == 2

    def test_preview_low_sample_warning(self, db_session):
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100)
        db_session.commit()
        result = cost_migration_service.preview_migration(db_session)
        assert result['low_sample_count'] == 1
        assert result['items'][0]['low_sample_warning'] is True


# ============================================================================
# 迁移执行测试
# ============================================================================

class TestMigrationExecute:
    def test_execute_creates_records(self, db_session):
        batch = _make_batch(db_session)
        for rate in [100, 110, 120]:
            _make_item(db_session, batch.id, unit_rate=rate)
        db_session.commit()
        result = cost_migration_service.execute_migration(
            db_session, operator='tester', reason='测试迁移', skip_gate_check=True)
        assert result['success'] is True
        assert result['created'] == 1
        record = db_session.query(CostCatalog).first()
        assert record is not None
        assert float(record.avg_rate) == pytest.approx(110.0, abs=0.01)
        assert record.sample_count == 3

    def test_execute_updates_existing(self, db_session):
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100)
        db_session.commit()
        cost_migration_service.execute_migration(
            db_session, operator='tester', reason='第一次', skip_gate_check=True)
        _make_item(db_session, batch.id, unit_rate=200)
        db_session.commit()
        result = cost_migration_service.execute_migration(
            db_session, operator='tester', reason='第二次', skip_gate_check=True)
        assert result['created'] == 0
        assert result['updated'] == 1
        record = db_session.query(CostCatalog).first()
        assert float(record.avg_rate) == 150.0
        assert record.sample_count == 2

    def test_execute_preserves_b_fields(self, db_session):
        """迁移保留人工标注：已有 std_name 不被覆盖。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100, item_name='原始名称')
        db_session.commit()
        cost_migration_service.execute_migration(
            db_session, operator='tester', reason='第一次', skip_gate_check=True)
        record = db_session.query(CostCatalog).first()
        assert record.std_name == '原始名称'
        # 人工修改
        record.std_name = '人工标注名称'
        db_session.commit()
        # 新增数据后第二次迁移
        _make_item(db_session, batch.id, unit_rate=200, item_name='新原始名称')
        db_session.commit()
        cost_migration_service.execute_migration(
            db_session, operator='tester', reason='第二次', skip_gate_check=True)
        record = db_session.query(CostCatalog).first()
        assert record.std_name == '人工标注名称'

    def test_execute_idempotent(self, db_session):
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100)
        db_session.commit()
        r1 = cost_migration_service.execute_migration(
            db_session, operator='tester', reason='第一次', skip_gate_check=True)
        r2 = cost_migration_service.execute_migration(
            db_session, operator='tester', reason='第二次', skip_gate_check=True)
        assert r1['created'] == 1
        assert r2['created'] == 0
        record = db_session.query(CostCatalog).first()
        assert float(record.avg_rate) == 100.0

    def test_execute_gate_blocks_when_not_passed(self, db_session):
        """空库覆盖率=0 < 80% → 拒绝迁移。"""
        result = cost_migration_service.execute_migration(
            db_session, operator='tester', reason='测试', skip_gate_check=False)
        assert result['success'] is False
        assert result['error'] == 'gate_not_passed'

    def test_execute_writes_audit(self, db_session):
        from app.models.audit_log import AuditLog
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100)
        db_session.commit()
        cost_migration_service.execute_migration(
            db_session, operator='tester', reason='审计测试', skip_gate_check=True)
        logs = db_session.query(AuditLog).filter(AuditLog.action == 'cost_migration').all()
        assert len(logs) >= 1
        assert logs[0].reason == '审计测试'


# ============================================================================
# API 层测试
# ============================================================================

class TestCostCatalogAPI:
    def test_list_requires_auth(self, client):
        resp = client.get("/api/cost-catalog/list")
        assert resp.status_code == 401

    def test_list_empty(self, client):
        resp = client.get("/api/cost-catalog/list", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()['data']['total'] == 0

    def test_list_with_data(self, client, db_session):
        record = CostCatalog(
            match_key='code:api:1', std_name='API测试', unit_std='m',
            avg_rate=100.0, sample_count=1)
        db_session.add(record)
        db_session.commit()
        resp = client.get("/api/cost-catalog/list", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()['data']['total'] == 1
        assert resp.json()['data']['items'][0]['std_name'] == 'API测试'

    def test_preview_requires_auth(self, client):
        resp = client.get("/api/cost-catalog/migrate/preview")
        assert resp.status_code == 401

    def test_execute_requires_reason(self, client):
        resp = client.post("/api/cost-catalog/migrate/execute",
                           json={}, headers=AUTH_HEADER)
        assert resp.status_code == 422

    def test_execute_gate_blocked(self, client, db_session):
        resp = client.post("/api/cost-catalog/migrate/execute",
                           json={"reason": "测试", "skip_gate_check": False},
                           headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()['success'] is False
        assert resp.json()['error'] == 'gate_not_passed'
