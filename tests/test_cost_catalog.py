# -*- coding: utf-8 -*-
"""M3.6 成本库评估门槛 Service + API 测试。

测试覆盖：
1. 空库 → 门槛未通过（coverage=0, anomaly=0 但 coverage<0.80）
2. 达标数据 → 门槛通过（coverage>=0.80 & anomaly<0.10）
3. 覆盖率不足 → blockers 提示
4. 异常率超标 → blockers 提示
5. 纯函数 evaluate_gate 边界（coverage=0.80 通过，anomaly=0.10 不通过）
6. API 路由可达性 + 权限
"""
import pytest
from datetime import date

from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.services import cost_catalog_service
from data.cost_catalog_gate import evaluate_gate, evaluate_gate_from_metrics

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
    defaults = {
        'item_code': '030404001001',
        'item_name': '测试项', 'item_feature': '测试特征',
        'unit': 'm', 'quantity': 100, 'unit_rate': 50.0, 'total': 5000,
        'data_source_type': 'completed', 'province': '辽宁',
        'price_period': date(2026, 3, 1), 'active': True,
        'match_key_source': 'code', 'anomaly_flag': 'normal',
    }
    defaults.update(kwargs)
    item = BoqItem(import_batch_id=batch_id, **defaults)
    db.add(item)
    db.flush()
    return item


# ============================================================================
# 纯函数层验证（data/cost_catalog_gate.py）
# ============================================================================

class TestPureGate:
    """cost_catalog_gate 纯函数验证。"""

    def test_passed_when_both_ok(self):
        """覆盖率 0.85 >= 0.80，异常率 0.05 < 0.10 → 通过。"""
        result = evaluate_gate(0.85, 0.05)
        assert result['passed'] is True
        assert result['coverage_ok'] is True
        assert result['anomaly_ok'] is True
        assert result['blockers'] == []

    def test_failed_when_coverage_low(self):
        """覆盖率 0.70 < 0.80 → 不通过，blockers 提示。"""
        result = evaluate_gate(0.70, 0.05)
        assert result['passed'] is False
        assert result['coverage_ok'] is False
        assert len(result['blockers']) == 1
        assert '覆盖率' in result['blockers'][0]

    def test_failed_when_anomaly_high(self):
        """异常率 0.15 >= 0.10 → 不通过。"""
        result = evaluate_gate(0.85, 0.15)
        assert result['passed'] is False
        assert result['anomaly_ok'] is False
        assert '异常率' in result['blockers'][0]

    def test_coverage_boundary_exactly_80(self):
        """覆盖率恰好 0.80 → 通过（>=）。"""
        result = evaluate_gate(0.80, 0.05)
        assert result['coverage_ok'] is True

    def test_anomaly_boundary_exactly_10(self):
        """异常率恰好 0.10 → 不通过（严格 <）。"""
        result = evaluate_gate(0.85, 0.10)
        assert result['anomaly_ok'] is False

    def test_both_failed_two_blockers(self):
        """双不达标 → 2 条 blockers。"""
        result = evaluate_gate(0.50, 0.20)
        assert result['passed'] is False
        assert len(result['blockers']) == 2

    def test_evaluate_from_metrics(self):
        """从 metrics dict 直接判定。"""
        metrics = {'coverage': 0.85, 'anomaly_rate': 0.05}
        result = evaluate_gate_from_metrics(metrics)
        assert result['passed'] is True

    def test_evaluate_from_empty_metrics(self):
        """空 metrics → coverage=0, anomaly=0 → 不通过（空库不得放行）。"""
        result = evaluate_gate_from_metrics({})
        assert result['passed'] is False
        assert result['coverage_ok'] is False


# ============================================================================
# Service 层测试
# ============================================================================

class TestCostCatalogService:
    """成本库评估 Service 测试。"""

    def test_empty_database_not_passed(self, db_session):
        """空库 → 门槛未通过（coverage=0）。"""
        result = cost_catalog_service.get_gate_status(db_session)
        assert result['success'] is True
        assert result['data']['gate']['passed'] is False
        assert '暂不建议' in result['data']['recommendation']

    def test_passed_with_good_data(self, db_session):
        """达标数据 → 门槛通过。"""
        batch = _make_batch(db_session)
        # 5 条中 4 条有 material_dict_id（coverage=0.80），0 条 error（anomaly=0）
        for i in range(4):
            _make_item(db_session, batch.id, material_dict_id=i+1,
                       match_key_source='dict', anomaly_flag='normal')
        _make_item(db_session, batch.id, material_dict_id=None,
                   match_key_source='code', anomaly_flag='normal')
        db_session.commit()

        result = cost_catalog_service.get_gate_status(db_session)
        assert result['success'] is True
        assert result['data']['metrics']['coverage'] == 0.8
        assert result['data']['metrics']['anomaly_rate'] == 0.0
        assert result['data']['gate']['passed'] is True
        assert '可以启动' in result['data']['recommendation']

    def test_not_passed_low_coverage(self, db_session):
        """覆盖率不足 → 不通过，blockers 提示。"""
        batch = _make_batch(db_session)
        # 3 条中 1 条有 dict（coverage=0.33）
        _make_item(db_session, batch.id, material_dict_id=1, match_key_source='dict')
        _make_item(db_session, batch.id, material_dict_id=None, match_key_source='code')
        _make_item(db_session, batch.id, material_dict_id=None, match_key_source='code')
        db_session.commit()

        result = cost_catalog_service.get_gate_status(db_session)
        assert result['data']['gate']['passed'] is False
        assert len(result['data']['gate']['blockers']) >= 1

    def test_not_passed_high_anomaly(self, db_session):
        """异常率超标 → 不通过。"""
        batch = _make_batch(db_session)
        # 5 条全有 dict（coverage=1.0），但 2 条 error（anomaly=0.40）
        for i in range(3):
            _make_item(db_session, batch.id, material_dict_id=i+1, anomaly_flag='normal')
        for i in range(2):
            _make_item(db_session, batch.id, material_dict_id=10+i, anomaly_flag='error')
        db_session.commit()

        result = cost_catalog_service.get_gate_status(db_session)
        assert result['data']['metrics']['anomaly_rate'] == 0.4
        assert result['data']['gate']['passed'] is False
        assert result['data']['gate']['anomaly_ok'] is False

    def test_gate_contains_metrics_and_gate(self, db_session):
        """返回结构包含 metrics 和 gate。"""
        result = cost_catalog_service.get_gate_status(db_session)
        assert 'metrics' in result['data']
        assert 'gate' in result['data']
        assert 'recommendation' in result['data']
        assert 'thresholds' in result['data']['gate']


# ============================================================================
# API 层测试
# ============================================================================

class TestCostCatalogAPI:
    """成本库评估 API 路由测试。"""

    def test_gate_requires_auth(self, client):
        """未授权 → 401。"""
        resp = client.get("/api/cost-catalog/gate")
        assert resp.status_code == 401

    def test_gate_empty(self, client):
        """空库 → 200，门槛未通过。"""
        resp = client.get("/api/cost-catalog/gate", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['gate']['passed'] is False

    def test_gate_with_data(self, client, db_session):
        """有数据 → 指标正确。"""
        batch = _make_batch(db_session)
        for i in range(4):
            _make_item(db_session, batch.id, material_dict_id=i+1, anomaly_flag='normal')
        _make_item(db_session, batch.id, material_dict_id=None, anomaly_flag='normal')
        db_session.commit()

        resp = client.get("/api/cost-catalog/gate", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['data']['metrics']['coverage'] == 0.8
        assert data['data']['gate']['passed'] is True
