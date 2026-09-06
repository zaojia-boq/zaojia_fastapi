# -*- coding: utf-8 -*-
"""M3.5 批量操作 API。

路由：
- POST /api/batch-ops/confirm-anomalies —— 批量修改 anomaly_flag（B 类，强制 reason）
- POST /api/batch-ops/switch-data-source —— 批量修改 data_source_type（B 类，completed 需二次确认）

权限：estimator + admin（B 类写操作，viewer 不可）。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user, require_role, ROLE_ESTIMATOR, ROLE_ADMIN
from app.services import batch_operation_service

router = APIRouter(prefix="/api/batch-ops", tags=["批量操作"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ConfirmAnomaliesRequest(BaseModel):
    """异常确认请求。"""
    operator: str = Field(..., description="操作人（OA 用户名）")
    reason: str = Field(..., description="变更原因（B 类字段必填）")
    item_ids: list[int] = Field(..., description="清单项 ID 列表")
    target_flag: str = Field(..., description="目标状态：normal 或 warning")
    require_confirm: bool = Field(False, description="二次确认（>50行或批量操作时必填）")


class SwitchDataSourceRequest(BaseModel):
    """数据性质切换请求。"""
    operator: str = Field(..., description="操作人（OA 用户名）")
    reason: str = Field(..., description="变更原因（B 类字段必填）")
    item_ids: list[int] = Field(..., description="清单项 ID 列表")
    target_type: str = Field(..., description="目标性质：completed/pending_review/control_price/bid_price/info_price")
    require_confirm: bool = Field(False, description="二次确认（切换到completed或>50行时必填）")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.post("/confirm-anomalies")
async def confirm_anomalies(
    req: ConfirmAnomaliesRequest,
    user=Depends(require_role(ROLE_ESTIMATOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """批量修改 anomaly_flag（B 类字段，强制 reason，逐字段写审计）。

    铁律：目标状态只允许 normal/warning（不允许直接设 error）；>50 行需二次确认。
    """
    payload = req.model_dump()
    result = batch_operation_service.confirm_anomalies(db, payload)
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/switch-data-source")
async def switch_data_source(
    req: SwitchDataSourceRequest,
    user=Depends(require_role(ROLE_ESTIMATOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """批量修改 data_source_type（B 类字段，强制 reason，逐字段写审计）。

    防污染闸门：切换到 completed 需 require_confirm=True（影响历史均价统计）。
    """
    payload = req.model_dump()
    result = batch_operation_service.switch_data_source(db, payload)
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result)
    return result
