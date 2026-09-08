# -*- coding: utf-8 -*-
"""常用项收藏 API（P3 体验增强）。

接口：
- POST /api/favorites/{item_id}：收藏条目
- DELETE /api/favorites/{item_id}：取消收藏
- GET /api/favorites：获取当前用户收藏列表（分页）
- GET /api/favorites/check/{item_id}：检查是否已收藏
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_role, ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER
from app.db import get_db
from app.models.favorite import UserFavorite
from app.models.boq_item import BoqItem

router = APIRouter(prefix="/api/favorites", tags=["收藏"])


def _get_username(user: dict) -> str:
    """从用户对象获取用户名。"""
    return user.get("username", "anonymous")


@router.post("/{item_id}")
def add_favorite(
    item_id: int,
    note: Optional[str] = Query(None, description="收藏备注"),
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """收藏清单项。

    同一用户对同一条目只能收藏一次（幂等）。
    """
    # 验证条目存在
    item = db.query(BoqItem).filter(BoqItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"清单项 {item_id} 不存在")

    username = _get_username(user)

    # 检查是否已收藏（幂等）
    existing = db.query(UserFavorite).filter(
        UserFavorite.username == username,
        UserFavorite.boq_item_id == item_id,
    ).first()
    if existing:
        return {"ok": True, "message": "已收藏", "favorite": existing.to_dict()}

    # 创建收藏
    fav = UserFavorite(
        username=username,
        boq_item_id=item_id,
        note=note,
    )
    db.add(fav)
    db.commit()
    db.refresh(fav)

    return {"ok": True, "message": "收藏成功", "favorite": fav.to_dict()}


@router.delete("/{item_id}")
def remove_favorite(
    item_id: int,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """取消收藏。"""
    username = _get_username(user)
    fav = db.query(UserFavorite).filter(
        UserFavorite.username == username,
        UserFavorite.boq_item_id == item_id,
    ).first()
    if not fav:
        raise HTTPException(status_code=404, detail="未收藏该条目")

    db.delete(fav)
    db.commit()
    return {"ok": True, "message": "已取消收藏"}


@router.get("")
def list_favorites(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """获取当前用户收藏列表（含清单项详情）。"""
    username = _get_username(user)
    offset = (page - 1) * page_size

    # 查询收藏（关联清单项）
    query = db.query(UserFavorite, BoqItem).join(
        BoqItem, UserFavorite.boq_item_id == BoqItem.id
    ).filter(
        UserFavorite.username == username,
    ).order_by(UserFavorite.created_at.desc())

    total = query.count()
    results = query.offset(offset).limit(page_size).all()

    items = []
    for fav, item in results:
        items.append({
            "favorite": fav.to_dict(),
            "boq_item": {
                "id": item.id,
                "item_code": item.item_code,
                "item_name": item.item_name,
                "item_feature": item.item_feature,
                "unit": item.unit,
                "quantity_num": item.quantity_num,
                "unit_rate_num": item.unit_rate_num,
                "total_num": item.total_num,
                "project_name": item.project_name,
                "price_period": item.price_period,
                "std_name": item.std_name,
            }
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/check/{item_id}")
def check_favorite(
    item_id: int,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER)),
    db: Session = Depends(get_db),
):
    """检查当前用户是否已收藏某条目。"""
    username = _get_username(user)
    fav = db.query(UserFavorite).filter(
        UserFavorite.username == username,
        UserFavorite.boq_item_id == item_id,
    ).first()
    return {"favorited": fav is not None, "favorite": fav.to_dict() if fav else None}
