# -*- coding: utf-8 -*-
"""M3.1 单价分析 Service + API 测试。

测试覆盖：
1. KPI 计算（空库 / 有数据 / 异常行识别）
2. 偏离判定（阈值 30% / 样本下限 3）
3. 四维度分组（aggregate_id / match_key_source / province / price_period）
4. 默认 completed 域隔离（pending_review 不计入均价）
5. API 路由可达性（/api/price/kpis / /api/price/analysis）
"""
import pytest
from datetime import date

from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.services import price_service
from data.price_calc import deviation_pct, is_anomaly, compute_kpis, analyze_group

DEV_TOKEN = "zaojia-dev-token-2026"
AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}


def _make_batch(db, name="test-batch", source_type="completed"):
    """创建测试批次。"""
    batch = ImportBatch(
        name=name,
        source_file=f"{name}.xlsx",
        file_hash="hash123",
        row_count=10,
        imported_count=10,
        skipped_count=0,
        anomaly_count=0,
        data_source_type=source_type,
        operator="tester",
    )
    db.add(batch)
    db.flush()
    return batch


def _make_item(db, batch_id, **kwargs):
    """创建测试清单项。"""
    defaults = {
        'item_code': '030404001001',
        'item_name': '测试项',
        'item_feature': '测试特征',
        'unit': 'm',
        'quantity': 100,
        'unit_rate': 50.0,
        'total': 5000,
        'data_source_type': 'completed',
        'province': '辽宁',
        'price_period': date(2026, 3, 1),
        'match_key': 'code:2013:030404001|m',
        'match_key_source': 'code',
        'aggregate_id': 'code:2013:030404001|m',
        'active': True,
    }
    defaults.update(kwargs)
    item = BoqItem(import_batch_id=batch_id, **defaults)
    db.add(item)
    db.flush()
    return item


# ============================================================================
# 纯函数层验证（data/price_calc.py）
# ============================================================================

class TestPureFunctions:
    """纯函数偏离判定验证。"""

    def test_deviation_pct_normal(self):
        """偏离百分比：(130-100)/100*100 = 30%。"""
        assert abs(deviation_pct(130, 100) - 30.0) < 0.01

    def test_deviation_pct_negative(self):
        """负偏离：(70-100)/100*100 = -30%。"""
        assert abs(deviation_pct(70, 100) - (-30.0)) < 0.01

    def test_deviation_pct_zero_avg(self):
        """均值为 0 时返回 0（避免除零）。"""
        assert deviation_pct(100, 0) == 0.0

    def test_is_anomaly_over_threshold(self):
        """偏离 67% > 30%，样本数 4 >= 3 → 异常。"""
        assert is_anomaly(200, 120, threshold=0.30, sample_count=4) is True

    def test_is_anomaly_within_threshold(self):
        """偏离 10% < 30% → 正常。"""
        assert is_anomaly(110, 100, threshold=0.30, sample_count=10) is False

    def test_is_anomaly_sample_below_min(self):
        """样本数 2 < 3 → 不判异常（统计不可靠）。"""
        assert is_anomaly(200, 100, threshold=0.30, sample_count=2) is False

    def test_compute_kpis_empty(self):
        """空数据 → 全 0。"""
        result = compute_kpis([])
        assert result['sample_count'] == 0
        assert result['avg'] == 0.0

    def test_compute_kpis_normal(self):
        """正常数据：[100, 110, 120, 200]，均值 132.5，200 偏离 50.9% 异常。"""
        rows = [{'unit_rate_num': v} for v in [100, 110, 120, 200]]
        result = compute_kpis(rows)
        assert result['sample_count'] == 4
        assert abs(result['avg'] - 132.5) < 0.01
        assert result['min'] == 100
        assert result['max'] == 200
        assert result['anomaly_count'] == 1  # 200 偏离 50.9% > 30%

    def test_analyze_group_invalid_key(self):
        """非法分组维度 → ValueError。"""
        with pytest.raises(ValueError):
            analyze_group([], 'invalid_dim')


# ============================================================================
# Service 层测试（app/services/price_service.py）
# ============================================================================

class TestPriceService:
    """单价分析 Service 测试。"""

    def test_get_kpis_empty(self, db_session):
        """空库 → sample_count=0。"""
        result = price_service.get_kpis(db_session)
        assert result['success'] is True
        assert result['data']['sample_count'] == 0
        assert result['total'] == 0

    def test_get_kpis_with_data(self, db_session):
        """有 completed 数据 → KPI 正确。"""
        batch = _make_batch(db_session)
        for rate in [100, 110, 120, 200]:
            _make_item(db_session, batch.id, unit_rate=rate, unit_rate_num=rate)
        db_session.commit()

        result = price_service.get_kpis(db_session)
        assert result['success'] is True
        assert result['data']['sample_count'] == 4
        assert abs(result['data']['avg'] - 132.5) < 0.01
        assert result['data']['anomaly_count'] == 1

    def test_get_kpis_completed_domain_isolation(self, db_session):
        """默认域只计 completed，pending_review 不计入。"""
        batch1 = _make_batch(db_session, name="completed-batch", source_type="completed")
        batch2 = _make_batch(db_session, name="pending-batch", source_type="pending_review")
        # completed: 2 条，均价 100
        _make_item(db_session, batch1.id, unit_rate=100, unit_rate_num=100, data_source_type='completed')
        _make_item(db_session, batch1.id, unit_rate=100, unit_rate_num=100, data_source_type='completed')
        # pending_review: 1 条，均价 999（不应计入）
        _make_item(db_session, batch2.id, unit_rate=999, unit_rate_num=999, data_source_type='pending_review')
        db_session.commit()

        result = price_service.get_kpis(db_session)
        assert result['success'] is True
        assert result['data']['sample_count'] == 2  # 只计 completed
        assert abs(result['data']['avg'] - 100.0) < 0.01

    def test_get_kpis_inactive_excluded(self, db_session):
        """active=False 的行不计入（统计口径纪律）。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100, unit_rate_num=100, active=True)
        _make_item(db_session, batch.id, unit_rate=200, unit_rate_num=200, active=False)
        db_session.commit()

        result = price_service.get_kpis(db_session)
        assert result['data']['sample_count'] == 1
        assert result['data']['avg'] == 100.0

    def test_get_analysis_four_dims(self, db_session):
        """四维度分组：每个维度都有结果。
        注意：aggregate_id 由 before_insert 事件监听器自动计算（基于 item_code），
        测试用不同 item_code 产生不同聚合组，不手动设置 aggregate_id。
        """
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100, unit_rate_num=100,
                    item_code='030404001001', province='辽宁',
                    price_period=date(2026, 3, 1), match_key_source='code')
        _make_item(db_session, batch.id, unit_rate=120, unit_rate_num=120,
                    item_code='030404002001', province='北京',
                    price_period=date(2026, 4, 1), match_key_source='std')
        db_session.commit()

        result = price_service.get_analysis(db_session)
        assert result['success'] is True
        data = result['data']
        assert 'aggregate_id' in data
        assert 'match_key_source' in data
        assert 'province' in data
        assert 'price_period' in data
        # aggregate_id 维度有 2 组（不同 item_code）
        agg_groups = data['aggregate_id']
        assert len(agg_groups) == 2

    def test_get_analysis_group_stats(self, db_session):
        """分组统计：每组 avg/min/max/count/anomaly_count 正确。
        用相同 item_code 产生相同 aggregate_id（事件监听器自动计算）。
        """
        batch = _make_batch(db_session)
        # 同 item_code 下 3 条：100/110/200，均值 136.7，200 异常
        for rate in [100, 110, 200]:
            _make_item(db_session, batch.id, unit_rate=rate, unit_rate_num=rate,
                        item_code='030404001001', match_key_source='code')
        db_session.commit()

        result = price_service.get_analysis(db_session)
        agg_data = result['data']['aggregate_id']
        # 只有 1 组（相同 item_code → 相同 aggregate_id）
        assert len(agg_data) == 1
        group = agg_data[0]
        assert group['count'] == 3
        assert abs(group['avg'] - 136.67) < 0.1
        assert group['min'] == 100
        assert group['max'] == 200
        assert group['anomaly_count'] == 1  # 200 偏离 46.3% > 30%


# ============================================================================
# API 层测试
# ============================================================================

class TestPriceAPI:
    """单价分析 API 路由测试。"""

    def test_kpis_api_requires_auth(self, client):
        """未授权 → 401。"""
        resp = client.get("/api/price/kpis")
        assert resp.status_code == 401

    def test_kpis_api_empty(self, client):
        """空库 → 200，sample_count=0。"""
        resp = client.get("/api/price/kpis", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['sample_count'] == 0

    def test_kpis_api_with_data(self, client, db_session):
        """有数据 → KPI 正确。"""
        batch = _make_batch(db_session)
        for rate in [100, 110, 120, 200]:
            _make_item(db_session, batch.id, unit_rate=rate, unit_rate_num=rate)
        db_session.commit()

        resp = client.get("/api/price/kpis", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['data']['sample_count'] == 4
        assert data['data']['anomaly_count'] == 1

    def test_analysis_api_requires_auth(self, client):
        """未授权 → 401。"""
        resp = client.get("/api/price/analysis")
        assert resp.status_code == 401

    def test_analysis_api_returns_four_dims(self, client, db_session):
        """分析 API 返回四维度。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100, unit_rate_num=100,
                    province='辽宁', aggregate_id='agg1')
        db_session.commit()

        resp = client.get("/api/price/analysis", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert 'aggregate_id' in data['data']
        assert 'province' in data['data']

    def test_kpis_api_province_filter(self, client, db_session):
        """按省份过滤。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, unit_rate=100, unit_rate_num=100, province='辽宁')
        _make_item(db_session, batch.id, unit_rate=200, unit_rate_num=200, province='北京')
        db_session.commit()

        resp = client.get("/api/price/kpis", headers=AUTH_HEADER, params={"province": "辽宁"})
        assert resp.status_code == 200
        assert resp.json()['data']['sample_count'] == 1
        assert resp.json()['data']['avg'] == 100.0
