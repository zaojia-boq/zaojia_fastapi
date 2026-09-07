# -*- coding: utf-8 -*-
"""M3.4 快速匹配 API。

路由：
- POST /api/match/find —— rapidfuzz 召回 Top-5 候选（只读）
- POST /api/match/confirm —— 人工确认回填 B 类字段 + 写审计日志

权限：
- find：三角色均可（只读视图）
- confirm：estimator + admin（B 类写操作，viewer 不可）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user, require_role, ROLE_ESTIMATOR, ROLE_ADMIN
from app.services import material_match_service

router = APIRouter(prefix="/api/match", tags=["快速匹配"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class FindRequest(BaseModel):
    """召回候选请求。"""
    boq_item_ids: list[int] = Field(..., description="待匹配的清单项 ID 列表")


class ConfirmItem(BaseModel):
    """单条确认项。"""
    boq_item_id: int
    dict_id: int
    fill_empty_only: bool = Field(False, description="仅填空模式（高置信时自动链接）")


class ConfirmRequest(BaseModel):
    """确认回填请求。"""
    operator: str = Field(..., description="操作人（OA 用户名）")
    reason: str = Field(..., description="变更原因（B 类字段必填）")
    items: list[ConfirmItem]


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.post("/find")
async def match_find(
    req: FindRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """rapidfuzz 召回 Top-5 候选（只读，不修改任何数据）。

    返回 {boq_item_id: [{dict_id, name, spec, score, category_path}, ...]}。
    """
    result = material_match_service.find_matches(db, req.boq_item_ids)
    return result


@router.post("/confirm")
async def match_confirm(
    req: ConfirmRequest,
    user=Depends(require_role(ROLE_ESTIMATOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """人工确认回填 B 类字段（std_name/std_spec/material_dict_id）。

    铁律：仅填空，绝不覆盖已有 B 类值；逐字段写 audit_log（append-only）；
    回填后 match_key 由 before_update 事件监听器自动重算。
    """
    payload = {
        'operator': req.operator,
        'reason': req.reason,
        'items': [item.model_dump() for item in req.items],
    }
    result = material_match_service.confirm_match(db, payload)
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result)
    return result


# ---------------------------------------------------------------------------
# 后台预匹配（性能优化）
# ---------------------------------------------------------------------------

class PrematchRequest(BaseModel):
    """预匹配请求。"""
    batch_id: int | None = Field(None, description="批次 ID（None 表示所有待匹配）")
    limit: int = Field(0, description="限制计算数量（0 表示不限制）")


@router.post("/prematch")
async def trigger_prematch(
    req: PrematchRequest,
    user=Depends(require_role(ROLE_ESTIMATOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """触发后台预匹配（异步）。导入完成后调用，预计算所有待匹配条目的候选。"""
    from app.services.prematch_service import precompute_pending_matches_async, get_prematch_status
    from app.db import SessionLocal

    precompute_pending_matches_async(SessionLocal, batch_id=req.batch_id, limit=req.limit)
    return {"success": True, "message": "预匹配任务已在后台启动", "status": get_prematch_status()}


@router.get("/prematch/status")
async def prematch_status(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看预匹配任务状态。"""
    from app.services.prematch_service import get_prematch_status
    return get_prematch_status()
