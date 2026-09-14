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
from sqlalchemy import func

from app.db import get_db
from app.core.security import get_current_user, require_role, ROLE_ADMIN, ROLE_ESTIMATOR
from app.core.audit import log_audit, ACTION_CREATE, ACTION_WRITE, ACTION_HARD_DELETE
from app.models.material_dict import MaterialDict
from app.models.boq_item import BoqItem

logger = logging.getLogger("zaojia.dict")

router = APIRouter(prefix="/api/dict", tags=["物料字典"])


class DictCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="分类名称")
    level: str = Field(..., pattern="^(l1|l2|l3|l4|l5)$", description="层级")
    parent_id: int | None = Field(None, description="父级 ID（l2-l5 必填）")
    synonyms: list[str] | None = Field(None, description="业务同义词列表")
    spec_whitelist: list[str] | None = Field(None, description="规格白名单列表")
    note: str | None = Field(None, max_length=1000, description="备注")
    # l5（规格叶子）专用字段
    spec: str | None = Field(None, max_length=200, description="规格（l5 必填）")
    model: str | None = Field(None, max_length=200, description="型号")
    unit: str | None = Field(None, max_length=50, description="单位")
    material: str | None = Field(None, max_length=200, description="材质")


class DictUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    synonyms: list[str] | None = None
    spec_whitelist: list[str] | None = None
    note: str | None = Field(None, max_length=1000)
    # l5（规格叶子）专用字段
    spec: str | None = Field(None, max_length=200)
    model: str | None = Field(None, max_length=200)
    unit: str | None = Field(None, max_length=50)
    material: str | None = Field(None, max_length=200)


def _generate_dict_code(db: Session, level: str, parent: MaterialDict | None) -> str:
    """自动生成五级编码。
    编码规则：l1=I+3位，l2=父编码+2位，l3=父编码+2位，l4=父编码+3位，l5=父编码+4位。
    查询同级最大编码+1，避免冲突。
    """
    # 各层级的序号位数
    digit_map = {"l1": 3, "l2": 2, "l3": 2, "l4": 3, "l5": 4}
    digits = digit_map[level]

    if level == "l1":
        prefix = "I"
        # 查询所有l1的最大编码
        max_node = db.query(MaterialDict).filter(
            MaterialDict.level == "l1",
            MaterialDict.code.isnot(None),
        ).order_by(MaterialDict.code.desc()).first()
        max_seq = 0
        if max_node and max_node.code:
            try:
                max_seq = int(max_node.code[1:])  # 去掉I前缀
            except (ValueError, IndexError):
                pass
        new_seq = max_seq + 1
        return f"{prefix}{new_seq:0{digits}d}"
    else:
        if not parent or not parent.code:
            # 父级无编码，用父级id生成临时编码
            return f"I{parent.id:03d}00" if parent else "I00000"
        prefix = parent.code
        # 查询同级（同父级）的最大编码
        max_node = db.query(MaterialDict).filter(
            MaterialDict.parent_id == parent.id,
            MaterialDict.code.isnot(None),
        ).order_by(MaterialDict.code.desc()).first()
        max_seq = 0
        if max_node and max_node.code:
            try:
                # 提取父编码后的序号部分
                suffix = max_node.code[len(prefix):]
                max_seq = int(suffix)
            except (ValueError, IndexError):
                pass
        new_seq = max_seq + 1
        return f"{prefix}{new_seq:0{digits}d}"


def _compute_cat_path(node: MaterialDict, db: Session) -> tuple[str | None, str | None, str | None]:
    # 收集祖先链
    chain = [node]
    current = node
    while current.parent_id:
        parent = db.query(MaterialDict).filter(MaterialDict.id == current.parent_id).first()
        if not parent:
            break
        chain.append(parent)
        current = parent
    chain.reverse()  # 从根到当前节点

    # 取前三级（l1/l2/l3）
    cat_l1 = chain[0].name if len(chain) >= 1 else None
    cat_l2 = chain[1].name if len(chain) >= 2 else None
    cat_l3 = chain[2].name if len(chain) >= 3 else None
    return cat_l1, cat_l2, cat_l3


@router.get("")
async def list_dict(
    level: str | None = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取所有物料分类（按层级分组），用于级联选择。
    level 参数可指定返回某一层级的所有节点（含 code 字段）。
    """
    if level:
        nodes = db.query(MaterialDict).filter(
            MaterialDict.level == level
        ).order_by(MaterialDict.code).all()
        return {
            "nodes": [
                {"id": n.id, "name": n.name, "code": n.code or "", "level": n.level, "parent_id": n.parent_id}
                for n in nodes
            ],
            "total": len(nodes),
        }
    all_nodes = db.query(MaterialDict).order_by(MaterialDict.level, MaterialDict.id).all()
    l1 = [{"id": n.id, "name": n.name, "code": n.code or ""} for n in all_nodes if n.level == "l1"]
    l2 = [{"id": n.id, "name": n.name, "code": n.code or "", "parent_id": n.parent_id} for n in all_nodes if n.level == "l2"]
    return {"l1": l1, "l2": l2, "total": len(all_nodes)}


@router.get("/children")
async def list_dict_children(
    parent_id: int | None = None,
    page: int = 1,
    page_size: int = 100,
    keyword: str | None = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按需加载子节点（懒加载树形结构用，支持分页和搜索过滤）。
    parent_id 为空时返回一级分类（l1）；否则返回指定节点的直接子节点。
    每个子节点包含 hasChild 标记，用于前端显示展开箭头。
    - page: 页码（从1开始）
    - page_size: 每页数量（默认100，最大500）
    - keyword: 名称关键词过滤（模糊匹配）
    """
    from sqlalchemy import exists, case

    page_size = min(max(page_size, 1), 500)
    page = max(page, 1)

    # 子查询：判断每个节点是否有子节点
    child_exists = exists().where(MaterialDict.parent_id == MaterialDict.id)

    base_query = db.query(MaterialDict).order_by(MaterialDict.name)

    if parent_id is None:
        base_query = base_query.filter(MaterialDict.parent_id.is_(None))
    else:
        base_query = base_query.filter(MaterialDict.parent_id == parent_id)

    if keyword:
        base_query = base_query.filter(MaterialDict.name.ilike(f"%{keyword}%"))

    # 总数
    total = base_query.count()

    # 分页查询
    rows = base_query.offset((page - 1) * page_size).limit(page_size).all()

    children = []
    for r in rows:
        # 批量判断hasChild（避免N+1查询）
        has_child = db.query(MaterialDict.id).filter(MaterialDict.parent_id == r.id).first() is not None
        children.append({
            "id": r.id,
            "name": r.name,
            "code": r.code or "",
            "level": r.level,
            "parent_id": r.parent_id,
            "hasChild": has_child,
        })

    return {
        "children": children,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.get("/tree/roots")
async def list_dict_roots(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取树形结构根节点（仅 l1 + l2 两级，用于初始快速渲染）。"""
    from sqlalchemy import exists, case

    child_exists = exists().where(MaterialDict.parent_id == MaterialDict.id)

    # 只查询 l1 和 l2（约 236 条，快速渲染）
    rows = db.query(
        MaterialDict.id,
        MaterialDict.name,
        MaterialDict.level,
        MaterialDict.parent_id,
        case((child_exists, True), else_=False).label("has_child"),
    ).filter(
        MaterialDict.level.in_(["l1", "l2"])
    ).order_by(MaterialDict.level, MaterialDict.name).all()

    tree = [
        {
            "id": r.id,
            "name": r.name,
            "level": r.level,
            "parent_id": r.parent_id,
            "hasChild": r.has_child,
            "loaded": r.level == "l2",  # l2 的子节点尚未加载
        }
        for r in rows
    ]

    total = db.query(func.count(MaterialDict.id)).scalar() or 0
    return {"tree": tree, "total": int(total)}


@router.post("")
async def create_dict(
    req: DictCreateRequest,
    user=Depends(require_role(ROLE_ADMIN, ROLE_ESTIMATOR)),
    db: Session = Depends(get_db),
):
    """新增物料分类。l2-l5 必须指定 parent_id；同级同名拒绝；自动生成五级编码。"""
    # 校验父级
    if req.level != "l1" and not req.parent_id:
        raise HTTPException(status_code=400, detail=f"{req.level} 层级必须指定 parent_id")
    if req.level == "l1" and req.parent_id:
        raise HTTPException(status_code=400, detail="l1 层级不能指定 parent_id")
    parent = None
    if req.parent_id:
        parent = db.query(MaterialDict).filter(MaterialDict.id == req.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail=f"父级分类 {req.parent_id} 不存在")
        # 父级层级必须是当前层级的上一级
        level_num = int(req.level[1])
        expected_parent_level = f"l{level_num - 1}"
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

    # l5 必须填写规格
    if req.level == "l5" and not req.spec:
        raise HTTPException(status_code=400, detail="五级（规格）必须填写规格")

    # 自动生成五级编码
    code = _generate_dict_code(db, req.level, parent)

    # 构建 synonyms（属性 dict 格式，与系统其他地方一致）
    synonyms_dict = None
    if req.level == "l5":
        synonyms_dict = {
            "材料名称": req.name,
            "规格": req.spec or "",
            "型号": req.model or "",
            "材质": req.material or "",
            "单位": req.unit or "",
        }
        if req.synonyms:
            synonyms_dict["同义词列表"] = req.synonyms
    elif req.synonyms:
        synonyms_dict = {"list": req.synonyms}

    # 构建 spec_whitelist
    spec_whitelist_dict = None
    if req.level == "l5" and req.spec:
        spec_whitelist_dict = {"规格": req.spec, "单位": req.unit or ""}
    elif req.spec_whitelist:
        spec_whitelist_dict = {"list": req.spec_whitelist}

    node = MaterialDict(
        name=req.name,
        level=req.level,
        parent_id=req.parent_id,
        code=code,
        synonyms=synonyms_dict,
        spec_whitelist=spec_whitelist_dict,
        note=req.note,
    )
    db.add(node)
    db.flush()  # 获取 id
    node.cat_l1, node.cat_l2, node.cat_l3 = _compute_cat_path(node, db)
    db.commit()
    db.refresh(node)

    log_audit(db, model="material_dict", res_id=node.id, action=ACTION_CREATE,
              operator=user.get("username", "unknown"), reason=f"新增分类：{req.name} ({req.level}, 编码={code})")
    db.commit()

    return {"success": True, "id": node.id, "name": node.name, "level": node.level, "code": code}


@router.get("/{dict_id}")
async def get_dict(dict_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """分类详情。"""
    node = db.query(MaterialDict).filter(MaterialDict.id == dict_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="分类不存在")
    # 解析 synonyms（支持属性 dict 和 list 两种格式）
    syn = node.synonyms if isinstance(node.synonyms, dict) else {}
    result = {
        "id": node.id, "name": node.name, "level": node.level,
        "parent_id": node.parent_id, "code": node.code,
        "cat_l1": node.cat_l1, "cat_l2": node.cat_l2, "cat_l3": node.cat_l3,
        "synonyms": syn.get("list", syn.get("同义词列表", [])) if isinstance(syn, dict) else [],
        "spec_whitelist": (node.spec_whitelist or {}).get("list", []) if isinstance(node.spec_whitelist, dict) else [],
        "note": node.note,
    }
    # l5 节点返回属性字段
    if node.level == "l5":
        result["spec"] = syn.get("规格", "")
        result["model"] = syn.get("型号", "")
        result["unit"] = syn.get("单位", "")
        result["material"] = syn.get("材质", "")
        result["material_name"] = syn.get("材料名称", "")
    return result


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
        # 保留 l5 的属性字段，只更新同义词列表
        if node.level == "l5" and isinstance(node.synonyms, dict):
            node.synonyms["同义词列表"] = req.synonyms
        else:
            node.synonyms = {"list": req.synonyms}
        changes.append(f"同义词→{len(req.synonyms)}个")
    if req.spec_whitelist is not None:
        node.spec_whitelist = {"list": req.spec_whitelist}
        changes.append(f"规格白名单→{len(req.spec_whitelist)}个")
    if req.note is not None:
        node.note = req.note
        changes.append("备注已更新")
    # l5 属性字段更新
    if node.level == "l5":
        syn = node.synonyms if isinstance(node.synonyms, dict) else {}
        if req.spec is not None:
            syn["规格"] = req.spec
            changes.append(f"规格→{req.spec}")
        if req.model is not None:
            syn["型号"] = req.model
            changes.append(f"型号→{req.model}")
        if req.unit is not None:
            syn["单位"] = req.unit
            changes.append(f"单位→{req.unit}")
        if req.material is not None:
            syn["材质"] = req.material
            changes.append(f"材质→{req.material}")
        if req.name is not None:
            syn["材料名称"] = req.name
        node.synonyms = syn
        # 同步更新 spec_whitelist
        if req.spec is not None or req.unit is not None:
            node.spec_whitelist = {
                "规格": syn.get("规格", ""),
                "单位": syn.get("单位", ""),
            }

    if not changes:
        return {"success": True, "message": "无变更"}

    db.commit()
    log_audit(db, model="material_dict", res_id=node.id, action=ACTION_WRITE,
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
    log_audit(db, model="material_dict", res_id=dict_id, action=ACTION_HARD_DELETE,
              operator=user.get("username", "unknown"), reason=f"删除分类：{name}")
    db.commit()
    return {"success": True, "id": dict_id, "name": name}
