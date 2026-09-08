# -*- coding: utf-8 -*-
"""标签分类 API 测试（P3 体验增强）。"""
import pytest

from app.config import settings
from app.models.tag import Tag, ItemTag
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


def _make_tag(db_session, name="重点项", color="#FF5733"):
    tag = Tag(name=name, color=color, created_by="dev_admin")
    db_session.add(tag)
    db_session.flush()
    return tag


class TestTagAPI:
    """标签 API 测试。"""

    def test_create_tag_success(self, client, db_session):
        """创建标签成功。"""
        resp = client.post("/api/tags", json={"name": "重点项", "color": "#FF5733"}, headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["tag"]["name"] == "重点项"

    def test_create_tag_duplicate(self, client, db_session):
        """创建重复标签：返回 400。"""
        _make_tag(db_session, name="重复标签")
        db_session.commit()

        resp = client.post("/api/tags", json={"name": "重复标签"}, headers=AUTH_HEADER)
        assert resp.status_code == 400

    def test_list_tags(self, client, db_session):
        """获取标签列表：含条目数统计。"""
        _make_tag(db_session, name="标签1")
        _make_tag(db_session, name="标签2")
        db_session.commit()

        resp = client.get("/api/tags", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_update_tag(self, client, db_session):
        """更新标签成功。"""
        tag = _make_tag(db_session, name="旧名称")
        db_session.commit()

        resp = client.put(f"/api/tags/{tag.id}", json={"name": "新名称", "color": "#00FF00"}, headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["tag"]["name"] == "新名称"
        assert resp.json()["tag"]["color"] == "#00FF00"

    def test_delete_tag(self, client, db_session):
        """删除标签成功（仅 admin）。"""
        tag = _make_tag(db_session, name="待删除")
        db_session.commit()

        resp = client.delete(f"/api/tags/{tag.id}", headers=AUTH_HEADER)
        assert resp.status_code == 200

        # 验证已删除
        tag = db_session.query(Tag).filter(Tag.name == "待删除").first()
        assert tag is None

    def test_add_item_tag(self, client, db_session):
        """给条目打标签成功。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        tag = _make_tag(db_session, name="打标签测试")
        db_session.commit()

        resp = client.post(f"/api/tags/{tag.id}/items/{item.id}", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 验证数据库
        item_tag = db_session.query(ItemTag).filter(
            ItemTag.tag_id == tag.id, ItemTag.boq_item_id == item.id
        ).first()
        assert item_tag is not None

    def test_add_item_tag_idempotent(self, client, db_session):
        """打标签幂等：重复打标签不报错。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        tag = _make_tag(db_session, name="幂等标签")
        db_session.commit()

        # 第一次
        resp1 = client.post(f"/api/tags/{tag.id}/items/{item.id}", headers=AUTH_HEADER)
        assert resp1.status_code == 200
        # 第二次（幂等）
        resp2 = client.post(f"/api/tags/{tag.id}/items/{item.id}", headers=AUTH_HEADER)
        assert resp2.status_code == 200
        assert "已打标签" in resp2.json()["message"]

        # 数据库只有一条记录
        count = db_session.query(ItemTag).filter(
            ItemTag.tag_id == tag.id, ItemTag.boq_item_id == item.id
        ).count()
        assert count == 1

    def test_remove_item_tag(self, client, db_session):
        """取消条目标签成功。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        tag = _make_tag(db_session, name="取消标签测试")
        db_session.commit()

        # 先打标签
        client.post(f"/api/tags/{tag.id}/items/{item.id}", headers=AUTH_HEADER)
        # 取消标签
        resp = client.delete(f"/api/tags/{tag.id}/items/{item.id}", headers=AUTH_HEADER)
        assert resp.status_code == 200

        # 验证已删除
        item_tag = db_session.query(ItemTag).filter(
            ItemTag.tag_id == tag.id, ItemTag.boq_item_id == item.id
        ).first()
        assert item_tag is None

    def test_list_tag_items(self, client, db_session):
        """获取某标签下的所有条目。"""
        batch = _make_batch(db_session)
        item1 = _make_item(db_session, batch.id, name="条目1", code="001")
        item2 = _make_item(db_session, batch.id, name="条目2", code="002")
        tag = _make_tag(db_session, name="列表测试")
        db_session.commit()

        # 给两个条目打标签
        client.post(f"/api/tags/{tag.id}/items/{item1.id}", headers=AUTH_HEADER)
        client.post(f"/api/tags/{tag.id}/items/{item2.id}", headers=AUTH_HEADER)

        # 获取标签下的条目
        resp = client.get(f"/api/tags/{tag.id}/items", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2
        assert len(resp.json()["items"]) == 2

    def test_list_item_tags(self, client, db_session):
        """获取某条目的所有标签。"""
        batch = _make_batch(db_session)
        item = _make_item(db_session, batch.id)
        tag1 = _make_tag(db_session, name="标签A")
        tag2 = _make_tag(db_session, name="标签B")
        db_session.commit()

        # 给条目打两个标签
        client.post(f"/api/tags/{tag1.id}/items/{item.id}", headers=AUTH_HEADER)
        client.post(f"/api/tags/{tag2.id}/items/{item.id}", headers=AUTH_HEADER)

        # 获取条目的标签
        resp = client.get(f"/api/tags/items/{item.id}/tags", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_tag_not_found(self, client, db_session):
        """操作不存在的标签：返回 404。"""
        resp = client.get("/api/tags/999999/items", headers=AUTH_HEADER)
        assert resp.status_code == 404

    def test_tag_requires_auth(self, client):
        """标签接口需要认证。"""
        resp = client.get("/api/tags")
        assert resp.status_code in (401, 403)
