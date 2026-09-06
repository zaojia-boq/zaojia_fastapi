# -*- coding: utf-8 -*-
"""M3.4 快速匹配 Service + API 测试。

测试覆盖：
1. find_matches：空库 / 有候选 / Top-5 限制 / 不存在的 ID
2. confirm_match：回填空字段 / 不覆盖已有 B 类值 / 写审计日志 / match_key 自动重算
3. API 路由：find 可达 / confirm 权限（viewer 不可）/ confirm 成功
"""
import pytest
from datetime import date

from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.models.material_dict import MaterialDict
from app.models.audit_log import AuditLog
from app.services import material_match_service

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


def _make_dict(db, name, cat_l1=None, cat_l2=None, cat_l3=None, level='l3'):
    """创建物料字典条目。"""
    d = MaterialDict(
        name=name, level=level,
        cat_l1=cat_l1, cat_l2=cat_l2, cat_l3=cat_l3,
    )
    db.add(d)
    db.flush()
    return d


def _make_item(db, batch_id, **kwargs):
    defaults = {
        'item_code': '030404001001',
        'item_name': '电力电缆',
        'item_feature': 'YJV 4*16',
        'unit': 'm', 'quantity': 100, 'unit_rate': 50.0, 'total': 5000,
        'data_source_type': 'completed', 'province': '辽宁',
        'price_period': date(2026, 3, 1), 'active': True,
    }
    defaults.update(kwargs)
    item = BoqItem(import_batch_id=batch_id, **defaults)
    db.add(item)
    db.flush()
    return item


# ============================================================================
# Service 层测试
# ============================================================================

class TestFindMatches:
    """find_matches 召回测试。"""

    def test_empty_ids(self, db_session):
        """空 ID 列表 → 空结果。"""
        result = material_match_service.find_matches(db_session, [])
        assert result['success'] is True
        assert result['data'] == {}
        assert result['total'] == 0

    def test_no_dict_rows(self, db_session):
        """无物料字典 → 候选为空。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        result = material_match_service.find_matches(db_session, [item.id])
        assert result['success'] is True
        assert result['data'][item.id] == []

    def test_recall_candidates(self, db_session):
        """有匹配字典 → 返回候选，按 score 降序。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, item_name='电力电缆', item_feature='YJV 4*16')
        # 创建匹配度高的字典
        _make_dict(db_session, '电力电缆', cat_l1='电气', cat_l2='电缆', cat_l3='YJV 4*16')
        # 创建匹配度低的字典
        _make_dict(db_session, '镀锌钢管', cat_l1='管道', cat_l2='钢管', cat_l3='DN100')
        db_session.commit()

        result = material_match_service.find_matches(db_session, [item.id])
        assert result['success'] is True
        cands = result['data'][item.id]
        assert len(cands) == 2
        # 按 score 降序
        assert cands[0]['score'] >= cands[1]['score']
        # Top-1 应该是电力电缆
        assert cands[0]['name'] == '电力电缆'
        assert 'dict_id' in cands[0]
        assert 'category_path' in cands[0]

    def test_top5_limit(self, db_session):
        """超过 5 个候选 → 只返回 Top-5。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, item_name='电缆', item_feature='YJV')
        for i in range(8):
            _make_dict(db_session, f'电缆{i}', cat_l1='电气', cat_l2='电缆', cat_l3=f'YJV{i}')
        db_session.commit()

        result = material_match_service.find_matches(db_session, [item.id])
        cands = result['data'][item.id]
        assert len(cands) == 5

    def test_nonexistent_id_warning(self, db_session):
        """不存在的 ID → warnings 提示。"""
        result = material_match_service.find_matches(db_session, [99999])
        assert result['success'] is True
        assert len(result['warnings']) == 1
        assert '99999' in result['warnings'][0]


class TestConfirmMatch:
    """confirm_match 回填测试。"""

    def test_invalid_payload_not_dict(self, db_session):
        """payload 非 dict → 错误。"""
        result = material_match_service.confirm_match(db_session, "not a dict")
        assert result['success'] is False
        assert result['error_code'] == 'MATCH_INVALID_PAYLOAD'

    def test_missing_fields(self, db_session):
        """缺少 operator/reason/items → 错误。"""
        result = material_match_service.confirm_match(db_session, {'operator': 'x'})
        assert result['success'] is False
        assert '缺少' in result['message']

    def test_fill_empty_fields(self, db_session):
        """回填空字段 → std_name/std_spec/material_dict_id 写入。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, item_name='电力电缆', item_feature='YJV 4*16')
        d = _make_dict(db_session, '电力电缆', cat_l1='电气', cat_l2='电缆', cat_l3='YJV 4*16')
        db_session.commit()

        payload = {
            'operator': 'tester',
            'reason': '快速匹配确认：电力电缆 → YJV 4*16',
            'items': [{'boq_item_id': item.id, 'dict_id': d.id}],
        }
        result = material_match_service.confirm_match(db_session, payload)
        assert result['success'] is True
        assert result['data']['filled'] == 1

        # 验证回填
        db_session.refresh(item)
        assert item.std_name == '电力电缆'
        assert item.std_spec == 'YJV 4*16'
        assert item.material_dict_id == d.id

    def test_never_override_existing_b_fields(self, db_session):
        """B 类字段已有值 → 不覆盖（核心安全铁律）。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id,
                          item_name='电力电缆', item_feature='YJV 4*16',
                          std_name='已有标准名', std_spec='已有规格', material_dict_id=999)
        d = _make_dict(db_session, '电力电缆', cat_l1='电气', cat_l2='电缆', cat_l3='YJV 4*16')
        db_session.commit()

        payload = {
            'operator': 'tester',
            'reason': '测试不覆盖',
            'items': [{'boq_item_id': item.id, 'dict_id': d.id}],
        }
        result = material_match_service.confirm_match(db_session, payload)
        assert result['success'] is True
        assert result['data']['filled'] == 0  # 没有可填的空字段
        assert result['data']['ignored'] == 1

        # 验证原值不变
        db_session.refresh(item)
        assert item.std_name == '已有标准名'
        assert item.std_spec == '已有规格'
        assert item.material_dict_id == 999

    def test_audit_log_written(self, db_session):
        """回填后写审计日志（逐字段，append-only）。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, item_name='电力电缆', item_feature='YJV 4*16')
        d = _make_dict(db_session, '电力电缆', cat_l1='电气', cat_l2='电缆', cat_l3='YJV 4*16')
        db_session.commit()

        payload = {
            'operator': 'tester',
            'reason': '快速匹配确认',
            'items': [{'boq_item_id': item.id, 'dict_id': d.id}],
        }
        result = material_match_service.confirm_match(db_session, payload)
        assert result['success'] is True

        # 验证审计日志（3 个字段 → 3 条日志）
        logs = db_session.query(AuditLog).filter(
            AuditLog.model == 'boq_item', AuditLog.res_id == item.id
        ).all()
        assert len(logs) == 3  # std_name / std_spec / material_dict_id
        for log in logs:
            assert log.action == 'write'
            assert log.operator == 'tester'
            assert log.reason == '快速匹配确认'
            assert log.trace_id == result['trace_id']
            assert log.field_name in ('std_name', 'std_spec', 'material_dict_id')

    def test_match_key_auto_recompute(self, db_session):
        """回填 material_dict_id 后 → match_key/aggregate_id 自动重算（before_update）。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id,
                          item_name='电力电缆', item_feature='YJV 4*16',
                          item_code='030404001001')
        d = _make_dict(db_session, '电力电缆', cat_l1='电气', cat_l2='电缆', cat_l3='YJV 4*16')
        db_session.commit()

        # 回填前 aggregate_id 基于 match_key（无 material_dict_id）
        old_agg = item.aggregate_id
        assert old_agg is not None

        payload = {
            'operator': 'tester',
            'reason': '测试重算',
            'items': [{'boq_item_id': item.id, 'dict_id': d.id}],
        }
        material_match_service.confirm_match(db_session, payload)
        db_session.refresh(item)

        # 回填后 aggregate_id 应为 dict:<id>
        assert item.aggregate_id == f'dict:{d.id}'
        assert item.match_key_source == 'dict'  # 有 material_dict_id → 来源为 dict

    def test_nonexistent_boq_item(self, db_session):
        """boq_item 不存在 → not_found。"""
        d = _make_dict(db_session, '测试')
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': 'x',
            'items': [{'boq_item_id': 99999, 'dict_id': d.id}],
        }
        result = material_match_service.confirm_match(db_session, payload)
        assert result['success'] is True
        assert result['data']['items'][0]['status'] == 'not_found'

    def test_nonexistent_dict(self, db_session):
        """material_dict 不存在 → dict_not_found。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': 'x',
            'items': [{'boq_item_id': item.id, 'dict_id': 99999}],
        }
        result = material_match_service.confirm_match(db_session, payload)
        assert result['data']['items'][0]['status'] == 'dict_not_found'


# ============================================================================
# API 层测试
# ============================================================================

class TestMatchAPI:
    """快速匹配 API 路由测试。"""

    def test_find_api_requires_auth(self, client):
        """未授权 → 401。"""
        resp = client.post("/api/match/find", json={"boq_item_ids": []})
        assert resp.status_code == 401

    def test_find_api_success(self, client, db_session):
        """召回 API 成功。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, item_name='电力电缆', item_feature='YJV')
        _make_dict(db_session, '电力电缆', cat_l1='电气', cat_l2='电缆', cat_l3='YJV')
        db_session.commit()

        resp = client.post("/api/match/find",
                           json={"boq_item_ids": [item.id]},
                           headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert str(item.id) in data['data'] or item.id in data['data']

    def test_confirm_api_requires_auth(self, client):
        """未授权 → 401。"""
        resp = client.post("/api/match/confirm", json={
            "operator": "x", "reason": "y", "items": []
        })
        assert resp.status_code == 401

    def test_confirm_api_success(self, client, db_session):
        """确认回填 API 成功。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, item_name='电力电缆', item_feature='YJV 4*16')
        d = _make_dict(db_session, '电力电缆', cat_l1='电气', cat_l2='电缆', cat_l3='YJV 4*16')
        db_session.commit()

        resp = client.post("/api/match/confirm", json={
            "operator": "tester",
            "reason": "API 测试确认",
            "items": [{"boq_item_id": item.id, "dict_id": d.id}],
        }, headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['filled'] == 1
