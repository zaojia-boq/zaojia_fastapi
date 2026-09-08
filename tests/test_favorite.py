# -*- coding: utf-8 -*-
"""常用项收藏 API 测试（P3 体验增强）。"""
import pytest

from app.config import settings
from app.models.favorite import UserFavorite
from app.models.boq_item import BoqItem
from app.models.import_batch import ImportBatch

DEV_TOKEN = getattr(settings, 'dev_token', 'zaojia-dev-token-2026')
AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}


def _make_batch(db_session, name="测试批次"):
    batch = ImportBatch(name=name, source_file="test.xlsx", file_hash="abc123", row_count=1)
    db_session.add(batch)
    db_session.flush()
    return batch


def _make_item(db_session, batch_id, name="镀锌钢管", code="030801001001"):
    item = BoqItem(
        import_batch_id=batch_id,
        item_code=code,
        item_name=name,
        item_feature="DN100",
        unit="m",
        quantity=100,
        unit_rate=78.5,
        total=7850,
        data_source_type="completed",
        province="辽宁",
        match_key_source="code",
        sequence=1,
    )
    db_session.add(item)
    db_session.flush()
    return item


class TestFavoriteAPI:
    """收藏 API 测试。"""

    def test_add_favorite_success(self, client, db_session):
        """收藏成功：返回 200，数据库有记录。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        resp = client.post(f"/api/favorites/{item.id}", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 验证数据库
        fav = db_session.query(UserFavorite).filter(
            UserFavorite.boq_item_id == item.id
        ).first()
        assert fav is not None
        assert fav.username == "dev_admin"  # dev_token 默认 dev_admin

    def test_add_favorite_idempotent(self, client, db_session):
        """收藏幂等：重复收藏不报错，返回已收藏。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        # 第一次收藏
        resp1 = client.post(f"/api/favorites/{item.id}", headers=AUTH_HEADER)
        assert resp1.status_code == 200

        # 第二次收藏（幂等）
        resp2 = client.post(f"/api/favorites/{item.id}", headers=AUTH_HEADER)
        assert resp2.status_code == 200
        assert "已收藏" in resp2.json()["message"]

        # 数据库只有一条记录
        count = db_session.query(UserFavorite).filter(
            UserFavorite.boq_item_id == item.id
        ).count()
        assert count == 1

    def test_add_favorite_item_not_found(self, client, db_session):
        """收藏不存在的条目：返回 404。"""
        resp = client.post("/api/favorites/999999", headers=AUTH_HEADER)
        assert resp.status_code == 404

    def test_remove_favorite_success(self, client, db_session):
        """取消收藏成功。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        # 先收藏
        client.post(f"/api/favorites/{item.id}", headers=AUTH_HEADER)

        # 取消收藏
        resp = client.delete(f"/api/favorites/{item.id}", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 验证数据库已删除
        fav = db_session.query(UserFavorite).filter(
            UserFavorite.boq_item_id == item.id
        ).first()
        assert fav is None

    def test_remove_favorite_not_found(self, client, db_session):
        """取消未收藏的条目：返回 404。"""
        resp = client.delete("/api/favorites/999999", headers=AUTH_HEADER)
        assert resp.status_code == 404

    def test_list_favorites(self, client, db_session):
        """获取收藏列表：含清单项详情。"""
        batch = _make_batch(db_session)
        item1 = _make_item(db_session, batch.id, name="镀锌钢管", code="001")
        item2 = _make_item(db_session, batch.id, name="焊接钢管", code="002")
        db_session.commit()

        # 收藏两个条目
        client.post(f"/api/favorites/{item1.id}", headers=AUTH_HEADER)
        client.post(f"/api/favorites/{item2.id}", headers=AUTH_HEADER)

        # 获取收藏列表
        resp = client.get("/api/favorites", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        # 验证含清单项详情
        assert data["items"][0]["boq_item"]["item_name"] in ["镀锌钢管", "焊接钢管"]

    def test_check_favorite_true(self, client, db_session):
        """检查已收藏：返回 favorited=True。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        db_session.commit()

        client.post(f"/api/favorites/{item.id}", headers=AUTH_HEADER)
        resp = client.get(f"/api/favorites/check/{item.id}", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["favorited"] is True

    def test_check_favorite_false(self, client, db_session):
        """检查未收藏：返回 favorited=False。"""
        resp = client.get("/api/favorites/check/999999", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["favorited"] is False

    def test_favorite_requires_auth(self, client):
        """收藏接口需要认证：未登录返回 401。"""
        resp = client.post("/api/favorites/1")
        assert resp.status_code in (401, 403)
