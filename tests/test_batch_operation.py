# -*- coding: utf-8 -*-
"""M3.5 批量操作 Service + API 测试。

测试覆盖：
1. 异常确认：修改 anomaly_flag，写审计
2. 异常确认：目标状态不允许 error
3. 异常确认：已是目标状态跳过
4. 数据性质切换：修改 data_source_type，写审计
5. 数据性质切换：切换到 completed 需二次确认（防污染闸门）
6. 批量 >50 行需二次确认
7. 无 reason 拒绝
8. 不存在的 ID 处理
9. API 权限（viewer 不可）
"""
import pytest
from datetime import date

from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.models.audit_log import AuditLog
from app.services import batch_operation_service

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
# 异常确认测试
# ============================================================================

class TestConfirmAnomalies:
    """异常行批量确认测试。"""

    def test_confirm_anomaly_to_normal(self, db_session):
        """异常行确认 → anomaly_flag 从 error 改为 normal，写审计。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, anomaly_flag='error')
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': '人工确认报价合理',
            'item_ids': [item.id], 'target_flag': 'normal',
        }
        result = batch_operation_service.confirm_anomalies(db_session, payload)
        assert result['success'] is True
        assert result['data']['updated'] == 1

        db_session.refresh(item)
        assert item.anomaly_flag == 'normal'

        # 审计日志
        logs = db_session.query(AuditLog).filter(
            AuditLog.model == 'boq_item', AuditLog.res_id == item.id,
            AuditLog.field_name == 'anomaly_flag',
        ).all()
        assert len(logs) == 1
        assert logs[0].old_value == 'error'
        assert logs[0].new_value == 'normal'
        assert logs[0].reason == '人工确认报价合理'

    def test_target_flag_not_allowed_error(self, db_session):
        """目标状态不允许 error。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, anomaly_flag='normal')
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': 'x',
            'item_ids': [item.id], 'target_flag': 'error',
        }
        result = batch_operation_service.confirm_anomalies(db_session, payload)
        assert result['success'] is False
        assert 'target_flag' in result['message']

    def test_skip_already_target(self, db_session):
        """已是目标状态 → 跳过。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, anomaly_flag='normal')
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': 'x',
            'item_ids': [item.id], 'target_flag': 'normal',
        }
        result = batch_operation_service.confirm_anomalies(db_session, payload)
        assert result['success'] is True
        assert result['data']['updated'] == 0
        assert result['data']['skipped'] == 1

    def test_missing_reason_rejected(self, db_session):
        """无 reason → 拒绝。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        payload = {'operator': 'tester', 'item_ids': [item.id], 'target_flag': 'normal'}
        result = batch_operation_service.confirm_anomalies(db_session, payload)
        assert result['success'] is False
        assert '缺少' in result['message']

    def test_nonexistent_id_warning(self, db_session):
        """不存在的 ID → warnings 提示。"""
        payload = {
            'operator': 'tester', 'reason': 'x',
            'item_ids': [99999], 'target_flag': 'normal',
        }
        result = batch_operation_service.confirm_anomalies(db_session, payload)
        assert result['success'] is True
        assert len(result['warnings']) == 1
        assert result['data']['not_found'] == [99999]

    def test_batch_over_50_requires_confirm(self, db_session):
        """批量 >50 行需 require_confirm=True。"""
        batch = _make_batch(db_session)
        ids = []
        for i in range(51):
            item = _make_item(db_session, batch.id, anomaly_flag='error',
                              item_code=f'030404001{i:03d}')
            ids.append(item.id)
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': 'x',
            'item_ids': ids, 'target_flag': 'normal',
            # 没有 require_confirm
        }
        result = batch_operation_service.confirm_anomalies(db_session, payload)
        assert result['success'] is False
        assert '二次确认' in result['message']

        # 加上 require_confirm 后成功
        payload['require_confirm'] = True
        result = batch_operation_service.confirm_anomalies(db_session, payload)
        assert result['success'] is True
        assert result['data']['updated'] == 51


# ============================================================================
# 数据性质切换测试
# ============================================================================

class TestSwitchDataSource:
    """数据性质批量切换测试。"""

    def test_switch_to_pending(self, db_session):
        """切换到 pending_review → 成功，写审计。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, data_source_type='completed')
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': '修正数据性质',
            'item_ids': [item.id], 'target_type': 'pending_review',
        }
        result = batch_operation_service.switch_data_source(db_session, payload)
        assert result['success'] is True
        assert result['data']['updated'] == 1

        db_session.refresh(item)
        assert item.data_source_type == 'pending_review'

        # 审计日志
        logs = db_session.query(AuditLog).filter(
            AuditLog.model == 'boq_item', AuditLog.res_id == item.id,
            AuditLog.field_name == 'data_source_type',
        ).all()
        assert len(logs) == 1
        assert logs[0].old_value == 'completed'
        assert logs[0].new_value == 'pending_review'

    def test_switch_to_completed_requires_confirm(self, db_session):
        """切换到 completed → 防污染闸门，需 require_confirm=True。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, data_source_type='pending_review')
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': '确认计入历史均价',
            'item_ids': [item.id], 'target_type': 'completed',
            # 没有 require_confirm
        }
        result = batch_operation_service.switch_data_source(db_session, payload)
        assert result['success'] is False
        assert 'completed' in result['message']
        assert '二次确认' in result['message']

        # 加上 require_confirm 后成功
        payload['require_confirm'] = True
        result = batch_operation_service.switch_data_source(db_session, payload)
        assert result['success'] is True
        assert result['data']['to_completed'] == 1
        assert len(result['warnings']) == 1  # 防污染警告

    def test_invalid_target_type(self, db_session):
        """非法 target_type → 拒绝。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': 'x',
            'item_ids': [item.id], 'target_type': 'invalid_type',
        }
        result = batch_operation_service.switch_data_source(db_session, payload)
        assert result['success'] is False

    def test_skip_same_type(self, db_session):
        """已是目标性质 → 跳过。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, data_source_type='completed')
        db_session.commit()

        payload = {
            'operator': 'tester', 'reason': 'x',
            'item_ids': [item.id], 'target_type': 'completed',
            'require_confirm': True,
        }
        result = batch_operation_service.switch_data_source(db_session, payload)
        assert result['success'] is True
        assert result['data']['updated'] == 0
        assert result['data']['skipped'] == 1


# ============================================================================
# API 层测试
# ============================================================================

class TestBatchOperationAPI:
    """批量操作 API 路由测试。"""

    def test_confirm_anomalies_requires_auth(self, client):
        """未授权 → 401。"""
        resp = client.post("/api/batch-ops/confirm-anomalies", json={
            "operator": "x", "reason": "y", "item_ids": [], "target_flag": "normal"
        })
        assert resp.status_code == 401

    def test_confirm_anomalies_api_success(self, client, db_session):
        """异常确认 API 成功。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, anomaly_flag='error')
        db_session.commit()

        resp = client.post("/api/batch-ops/confirm-anomalies", json={
            "operator": "tester", "reason": "API测试确认",
            "item_ids": [item.id], "target_flag": "normal",
        }, headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['updated'] == 1

    def test_switch_data_source_api_success(self, client, db_session):
        """数据性质切换 API 成功。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id, data_source_type='completed')
        db_session.commit()

        resp = client.post("/api/batch-ops/switch-data-source", json={
            "operator": "tester", "reason": "API测试切换",
            "item_ids": [item.id], "target_type": "pending_review",
        }, headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['updated'] == 1

    def test_switch_to_completed_api_requires_confirm(self, client, db_session):
        """切换到 completed API 需二次确认。"""
        batch = _make_batch(db_session)
        item = _make_batch(db_session)
        item = _make_item(db_session, batch.id, data_source_type='pending_review')
        db_session.commit()

        resp = client.post("/api/batch-ops/switch-data-source", json={
            "operator": "tester", "reason": "x",
            "item_ids": [item.id], "target_type": "completed",
        }, headers=AUTH_HEADER)
        assert resp.status_code == 400  # 防污染闸门拒绝
