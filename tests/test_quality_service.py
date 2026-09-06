# -*- coding: utf-8 -*-
"""M3.2 数据质量仪表盘 Service + API 测试。

测试覆盖：
1. 空库 → 全 0，m3_pass/m4_pass False
2. 覆盖率计算（material_dict_id 非空占比）
3. 匹配质量计算（match_key_source ∈ {dict, std} 占比）
4. 数据性质分布（data_source_dist）
5. 异常率计算（anomaly_flag == 'error' 占比）
6. 达标门判定（m3_pass: coverage>=0.70 & anomaly<0.15; m4_pass: coverage>=0.80 & anomaly<0.10）
7. API 路由可达性 + 权限
"""
import pytest
from datetime import date

from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.services import data_quality_service
from data.quality_metrics import compute_metrics, M3_COVERAGE_MIN, M4_COVERAGE_MIN

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
# 纯函数层验证（data/quality_metrics.py）
# ============================================================================

class TestPureMetrics:
    """quality_metrics 纯函数验证。"""

    def test_empty_rows(self):
        """空数据 → 全 0，m3_pass/m4_pass False。"""
        result = compute_metrics([])
        assert result['coverage'] == 0.0
        assert result['match_key_quality'] == 0.0
        assert result['data_source_dist'] == {}
        assert result['anomaly_rate'] == 0.0
        assert result['m3_pass'] is False
        assert result['m4_pass'] is False

    def test_coverage_calculation(self):
        """覆盖率：material_dict_id 非空占比。"""
        rows = [
            {'material_dict_id': 1, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
        ]
        result = compute_metrics(rows)
        assert result['coverage'] == 0.5  # 1/2

    def test_match_key_quality(self):
        """匹配质量：dict/std 占比。"""
        rows = [
            {'material_dict_id': 1, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 2, 'match_key_source': 'std', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
        ]
        result = compute_metrics(rows)
        assert result['match_key_quality'] == pytest.approx(2/3, abs=0.01)

    def test_data_source_dist(self):
        """数据性质分布。"""
        rows = [
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'pending_review', 'anomaly_flag': 'normal'},
        ]
        result = compute_metrics(rows)
        assert result['data_source_dist']['completed'] == 2
        assert result['data_source_dist']['pending_review'] == 1

    def test_anomaly_rate(self):
        """异常率：anomaly_flag == 'error' 占比。"""
        rows = [
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'error'},
        ]
        result = compute_metrics(rows)
        assert result['anomaly_rate'] == 0.5

    def test_m3_pass_true(self):
        """M3 达标：coverage>=0.70 & anomaly<0.15。"""
        rows = [
            {'material_dict_id': 1, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 2, 'match_key_source': 'std', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
        ]
        result = compute_metrics(rows)
        # coverage = 2/3 = 0.667 < 0.70 → m3_pass False
        assert result['m3_pass'] is False

    def test_m3_pass_with_high_coverage(self):
        """M3 达标：coverage 80%，anomaly 0% → True。"""
        rows = [
            {'material_dict_id': 1, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 2, 'match_key_source': 'std', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 3, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
        ]
        result = compute_metrics(rows)
        assert result['coverage'] == 0.6  # 3/5
        assert result['m3_pass'] is False  # 0.6 < 0.70

    def test_m4_pass_stricter(self):
        """M4 门槛更严：coverage>=0.80 & anomaly<0.10。"""
        rows = [
            {'material_dict_id': 1, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 2, 'match_key_source': 'std', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 3, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 4, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': None, 'match_key_source': 'code', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
        ]
        result = compute_metrics(rows)
        assert result['coverage'] == 0.8  # 4/5
        assert result['anomaly_rate'] == 0.0
        assert result['m3_pass'] is True   # 0.8 >= 0.70
        assert result['m4_pass'] is True   # 0.8 >= 0.80


# ============================================================================
# Service 层测试
# ============================================================================

class TestQualityService:
    """数据质量 Service 测试。"""

    def test_empty_database(self, db_session):
        """空库 → 全 0。"""
        result = data_quality_service.get_dashboard(db_session)
        assert result['success'] is True
        assert result['total'] == 0
        assert result['data']['coverage'] == 0.0
        assert result['data']['m3_pass'] is False

    def test_coverage_with_data(self, db_session):
        """有数据 → 覆盖率正确。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, material_dict_id=1, match_key_source='dict')
        _make_item(db_session, batch.id, material_dict_id=None, match_key_source='code')
        db_session.commit()

        result = data_quality_service.get_dashboard(db_session)
        assert result['success'] is True
        assert result['total'] == 2
        assert result['data']['coverage'] == 0.5

    def test_match_key_quality(self, db_session):
        """匹配质量：dict/std 占比。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, material_dict_id=1, match_key_source='dict')
        _make_item(db_session, batch.id, material_dict_id=2, match_key_source='std')
        _make_item(db_session, batch.id, material_dict_id=None, match_key_source='code')
        db_session.commit()

        result = data_quality_service.get_dashboard(db_session)
        assert result['data']['match_key_quality'] == pytest.approx(2/3, abs=0.01)

    def test_data_source_dist(self, db_session):
        """数据性质分布。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, data_source_type='completed')
        _make_item(db_session, batch.id, data_source_type='completed')
        _make_item(db_session, batch.id, data_source_type='pending_review')
        db_session.commit()

        result = data_quality_service.get_dashboard(db_session)
        dist = result['data']['data_source_dist']
        assert dist.get('completed') == 2
        assert dist.get('pending_review') == 1

    def test_anomaly_rate(self, db_session):
        """异常率计算。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, anomaly_flag='normal')
        _make_item(db_session, batch.id, anomaly_flag='error')
        db_session.commit()

        result = data_quality_service.get_dashboard(db_session)
        assert result['data']['anomaly_rate'] == 0.5

    def test_active_only_filter(self, db_session):
        """active_only=True 时排除 active=False 的行。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, active=True, material_dict_id=1)
        _make_item(db_session, batch.id, active=False, material_dict_id=None)
        db_session.commit()

        result = data_quality_service.get_dashboard(db_session, active_only=True)
        assert result['total'] == 1  # 只计 active=True
        assert result['data']['coverage'] == 1.0

    def test_deviation_threshold_default(self, db_session):
        """偏差阈值默认 30。"""
        result = data_quality_service.get_dashboard(db_session)
        assert result['data']['deviation_threshold'] == 30


# ============================================================================
# API 层测试
# ============================================================================

class TestQualityAPI:
    """数据质量 API 路由测试。"""

    def test_dashboard_requires_auth(self, client):
        """未授权 → 401。"""
        resp = client.get("/api/quality/dashboard")
        assert resp.status_code == 401

    def test_dashboard_empty(self, client):
        """空库 → 200，全 0。"""
        resp = client.get("/api/quality/dashboard", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['total'] == 0
        assert data['data']['coverage'] == 0.0

    def test_dashboard_with_data(self, client, db_session):
        """有数据 → 指标正确。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, material_dict_id=1, match_key_source='dict')
        _make_item(db_session, batch.id, material_dict_id=None, match_key_source='code')
        db_session.commit()

        resp = client.get("/api/quality/dashboard", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 2
        assert data['data']['coverage'] == 0.5
        assert 'm3_pass' in data['data']
        assert 'm4_pass' in data['data']
        assert 'deviation_threshold' in data['data']
