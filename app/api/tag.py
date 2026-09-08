# -*- coding: utf-8 -*-
"""标签分类 API（P3 体验增强）。

接口：
- GET /api/tags：获取所有标签
- POST /api/tags：创建标签
- PUT /api/tags/{tag_id}：更新标签
- DELETE /api/tags/{tag_id}：删除标签
- POST /api/tags/{tag_id}/items/{item_id}：给条目打标签
- DELETE /api/tags/{tag_id}/items/{item_id}：取消标签
- GET /api/tags/{tag_id}/items：获取某标签下的所有条目
- GET /api/items/{item_id}/tags：获取某条目的所有标签
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import require_role, ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER
from app.db import get_db
from app.models.tag import Tag, ItemTag
from app.models.boq_item import BoqItem

router = APIRouter(prefix="/api/tags", tags=["标签"])


def _get_username(user: dict) -> str:
    """从用户对象获取用户名。"""
    return user.get("username", "anonymous")


class TagCreate(BaseModel):
    """创建标签请求。"""
    name: str
    color: Optional[str] = "#4D7CFE"
    description: Optional[str] = None


class TagUpdate(BaseModel):
    """更新标签请求。"""
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


@router.get("")
def list_tags(
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """获取所有标签（含条目数统计）。"""
    tags = db.query(Tag).order_by(Tag.name).all()
    result = []
    for tag in tags:
        item_count = db.query(ItemTag).filter(ItemTag.tag_id == tag.id).count()
        tag_dict = tag.to_dict()
        tag_dict["item_count"] = item_count
        result.append(tag_dict)
    return {"tags": result, "total": len(result)}


@router.post("")
def create_tag(
    body: TagCreate,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR)),
    db: Session = Depends(get_db),
):
    """创建标签（admin/estimator 可创建）。"""
    # 检查名称唯一性
    existing = db.query(Tag).filter(Tag.name == body.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"标签「{body.name}」已存在")

    tag = Tag(
        name=body.name,
        color=body.color or "#4D7CFE",
        description=body.description,
        created_by=_get_username(user),
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return {"ok": True, "tag": tag.to_dict()}


@router.put("/{tag_id}")
def update_tag(
    tag_id: int,
    body: TagUpdate,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR)),
    db: Session = Depends(get_db),
):
    """更新标签。"""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    if body.name is not None:
        # 检查名称唯一性（排除自身）
        existing = db.query(Tag).filter(Tag.name == body.name, Tag.id != tag_id).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"标签「{body.name}」已存在")
        tag.name = body.name
    if body.color is not None:
        tag.color = body.color
    if body.description is not None:
        tag.description = body.description

    db.commit()
    db.refresh(tag)
    return {"ok": True, "tag": tag.to_dict()}


@router.delete("/{tag_id}")
def delete_tag(
    tag_id: int,
    user=Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """删除标签（仅 admin，级联删除条目关联）。"""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    db.delete(tag)
    db.commit()
    return {"ok": True, "message": "标签已删除"}


@router.post("/{tag_id}/items/{item_id}")
def add_item_tag(
    tag_id: int,
    item_id: int,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """给条目打标签（幂等）。"""
    # 验证标签和条目存在
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")
    item = db.query(BoqItem).filter(BoqItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="清单项不存在")

    username = _get_username(user)

    # 检查是否已打标签（幂等）
    existing = db.query(ItemTag).filter(
        ItemTag.tag_id == tag_id,
        ItemTag.boq_item_id == item_id,
        ItemTag.username == username,
    ).first()
    if existing:
        return {"ok": True, "message": "已打标签", "item_tag": existing.to_dict()}

    item_tag = ItemTag(
        tag_id=tag_id,
        boq_item_id=item_id,
        username=username,
    )
    db.add(item_tag)
    db.commit()
    db.refresh(item_tag)
    return {"ok": True, "message": "打标签成功", "item_tag": item_tag.to_dict()}


@router.delete("/{tag_id}/items/{item_id}")
def remove_item_tag(
    tag_id: int,
    item_id: int,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """取消条目标签。"""
    username = _get_username(user)
    item_tag = db.query(ItemTag).filter(
        ItemTag.tag_id == tag_id,
        ItemTag.boq_item_id == item_id,
        ItemTag.username == username,
    ).first()
    if not item_tag:
        raise HTTPException(status_code=404, detail="未打该标签")

    db.delete(item_tag)
    db.commit()
    return {"ok": True, "message": "已取消标签"}


@router.get("/{tag_id}/items")
def list_tag_items(
    tag_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """获取某标签下的所有条目（当前用户打的标签）。"""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    username = _get_username(user)
    offset = (page - 1) * page_size

    query = db.query(ItemTag, BoqItem).join(
        BoqItem, ItemTag.boq_item_id == BoqItem.id
    ).filter(
        ItemTag.tag_id == tag_id,
        ItemTag.username == username,
    ).order_by(ItemTag.created_at.desc())

    total = query.count()
    results = query.offset(offset).limit(page_size).all()

    items = []
    for item_tag, item in results:
        items.append({
            "item_tag": item_tag.to_dict(),
            "boq_item": {
                "id": item.id,
                "item_code": item.item_code,
                "item_name": item.item_name,
                "item_feature": item.item_feature,
                "unit": item.unit,
                "quantity": item.quantity,
                "unit_rate": item.unit_rate,
                "total": item.total,
                "project_name": item.project_name,
                "price_period": item.price_period,
            }
        })

    return {
        "tag": tag.to_dict(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/items/{item_id}/tags")
def list_item_tags(
    item_id: int,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """获取某条目的所有标签（当前用户打的）。"""
    username = _get_username(user)
    item_tags = db.query(ItemTag).filter(
        ItemTag.boq_item_id == item_id,
        ItemTag.username == username,
    ).all()

    tags = []
    for item_tag in item_tags:
        tag = db.query(Tag).filter(Tag.id == item_tag.tag_id).first()
        if tag:
            tag_dict = tag.to_dict()
            tag_dict["tagged_at"] = item_tag.created_at.isoformat() if item_tag.created_at else None
            tags.append(tag_dict)

    return {"item_id": item_id, "tags": tags, "total": len(tags)}
