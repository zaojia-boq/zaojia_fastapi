# -*- coding: utf-8 -*-
"""物料字典 CRUD API（M4-标准维护 实现）。

路由：
- POST /api/dict/ —— 新增分类（l1/l2/l3）
- GET /api/dict/{id} —— 分类详情
- PUT /api/dict/{id} —— 更新分类（名称/同义词/规格白名单/备注）
- DELETE /api/dict/{id} —— 删除分类（有子级或被引用时拒绝）

设计来源：原 Odoo 版 zaojia.material.dict 的 CRUD。
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user, require_role, ROLE_ADMIN, ROLE_ESTIMATOR
from app.core.audit import log_audit, ACTION_CREATE, ACTION_WRITE, ACTION_HARD_DELETE
from app.models.material_dict import MaterialDict
from app.models.boq_item import BoqItem

logger = logging.getLogger("zaojia.dict")

router = APIRouter(prefix="/api/dict", tags=["物料字典"])


class DictCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="分类名称")
    level: str = Field(..., pattern="^(l1|l2|l3)$", description="层级")
    parent_id: int | None = Field(None, description="父级 ID（l2/l3 必填）")
    synonyms: list[str] | None = Field(None, description="业务同义词列表")
    spec_whitelist: list[str] | None = Field(None, description="规格白名单列表")
    note: str | None = Field(None, max_length=1000, description="备注")


class DictUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    synonyms: list[str] | None = None
    spec_whitelist: list[str] | None = None
    note: str | None = Field(None, max_length=1000)


def _compute_cat_path(node: MaterialDict, db: Session) -> tuple[str | None, str | None, str | None]:
    """根据父链计算 cat_l1/l2/l3（冗余平铺字段）。"""
    if node.level == "l1":
        return node.name, None, None
    parent = db.query(MaterialDict).filter(MaterialDict.id == node.parent_id).first()
    if not parent:
        return None, None, None
    if node.level == "l2":
        return parent.cat_l1 or parent.name, node.name, None
    if node.level == "l3":
        return parent.cat_l1, parent.cat_l2 or parent.name, node.name
    return None, None, None


@router.post("")
async def create_dict(
    req: DictCreateRequest,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR)),
    db: Session = Depends(get_db),
):
    """新增物料分类。l2/l3 必须指定 parent_id；同级同名拒绝。"""
    # 校验父级
    if req.level in ("l2", "l3") and not req.parent_id:
        raise HTTPException(status_code=400, detail=f"{req.level} 层级必须指定 parent_id")
    if req.level == "l1" and req.parent_id:
        raise HTTPException(status_code=400, detail="l1 层级不能指定 parent_id")
    if req.parent_id:
        parent = db.query(MaterialDict).filter(MaterialDict.id == req.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail=f"父级分类 {req.parent_id} 不存在")
        expected_parent_level = "l1" if req.level == "l2" else "l2"
        if parent.level != expected_parent_level:
            raise HTTPException(status_code=400, detail=f"{req.level} 的父级必须是 {expected_parent_level}")

    # 同级同名检查
    dup = db.query(MaterialDict).filter(
        MaterialDict.name == req.name,
        MaterialDict.level == req.level,
        MaterialDict.parent_id == (req.parent_id if req.parent_id else None),
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail=f"同级已存在同名分类：{req.name}")

    node = MaterialDict(
        name=req.name,
        level=req.level,
        parent_id=req.parent_id,
        synonyms={"list": req.synonyms} if req.synonyms else None,
        spec_whitelist={"list": req.spec_whitelist} if req.spec_whitelist else None,
        note=req.note,
    )
    db.add(node)
    db.flush()  # 获取 id
    node.cat_l1, node.cat_l2, node.cat_l3 = _compute_cat_path(node, db)
    db.commit()
    db.refresh(node)

    log_audit(db, action=ACTION_CREATE, entity_type="material_dict", entity_id=node.id,
              operator=user.get("username", "unknown"), reason=f"新增分类：{req.name} ({req.level})")
    db.commit()

    return {"success": True, "id": node.id, "name": node.name, "level": node.level}


@router.get("/{dict_id}")
async def get_dict(dict_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """分类详情。"""
    node = db.query(MaterialDict).filter(MaterialDict.id == dict_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="分类不存在")
    return {
        "id": node.id, "name": node.name, "level": node.level,
        "parent_id": node.parent_id, "cat_l1": node.cat_l1, "cat_l2": node.cat_l2, "cat_l3": node.cat_l3,
        "synonyms": (node.synonyms or {}).get("list", []) if isinstance(node.synonyms, dict) else [],
        "spec_whitelist": (node.spec_whitelist or {}).get("list", []) if isinstance(node.spec_whitelist, dict) else [],
        "note": node.note,
    }


@router.put("/{dict_id}")
async def update_dict(
    dict_id: int,
    req: DictUpdateRequest,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR)),
    db: Session = Depends(get_db),
):
    """更新分类（名称/同义词/规格白名单/备注）。"""
    node = db.query(MaterialDict).filter(MaterialDict.id == dict_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="分类不存在")

    changes = []
    if req.name is not None and req.name != node.name:
        node.name = req.name
        node.cat_l1, node.cat_l2, node.cat_l3 = _compute_cat_path(node, db)
        changes.append(f"名称→{req.name}")
    if req.synonyms is not None:
        node.synonyms = {"list": req.synonyms}
        changes.append(f"同义词→{len(req.synonyms)}个")
    if req.spec_whitelist is not None:
        node.spec_whitelist = {"list": req.spec_whitelist}
        changes.append(f"规格白名单→{len(req.spec_whitelist)}个")
    if req.note is not None:
        node.note = req.note
        changes.append("备注已更新")

    if not changes:
        return {"success": True, "message": "无变更"}

    db.commit()
    log_audit(db, action=ACTION_WRITE, entity_type="material_dict", entity_id=node.id,
              operator=user.get("username", "unknown"), reason="; ".join(changes))
    db.commit()
    return {"success": True, "id": node.id, "changes": changes}


@router.delete("/{dict_id}")
async def delete_dict(
    dict_id: int,
    user=Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """删除分类。有子级或被 boq_item 引用时拒绝。"""
    node = db.query(MaterialDict).filter(MaterialDict.id == dict_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="分类不存在")

    # 有子级拒绝
    child_count = db.query(MaterialDict).filter(MaterialDict.parent_id == dict_id).count()
    if child_count > 0:
        raise HTTPException(status_code=409, detail=f"该分类有 {child_count} 个子级，禁止删除")

    # 被引用拒绝
    ref_count = db.query(BoqItem).filter(BoqItem.material_dict_id == dict_id).count()
    if ref_count > 0:
        raise HTTPException(status_code=409, detail=f"该分类被 {ref_count} 条清单项引用，禁止删除")

    name = node.name
    db.delete(node)
    db.commit()
    log_audit(db, action=ACTION_HARD_DELETE, entity_type="material_dict", entity_id=dict_id,
              operator=user.get("username", "unknown"), reason=f"删除分类：{name}")
    db.commit()
    return {"success": True, "id": dict_id, "name": name}
