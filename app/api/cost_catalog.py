# -*- coding: utf-8 -*-
"""M3.6 成本库评估门槛 + M4.2 迁移服务 API。

路由：
- GET  /api/cost-catalog/gate —— M4 启动门槛评估（双门槛）
- GET  /api/cost-catalog/list —— 成本库列表（只读）
- GET  /api/cost-catalog/migrate/preview —— 迁移预览（不写库）
- POST /api/cost-catalog/migrate/execute —— 执行迁移（estimator+admin）

权限：gate/list 三角色均可；preview/execute 要求 estimator+admin。
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user, require_role, ROLE_ESTIMATOR, ROLE_ADMIN
from app.services import cost_catalog_service, cost_migration_service

router = APIRouter(prefix="/api/cost-catalog", tags=["成本库与迁移"])


class MigrationExecuteRequest(BaseModel):
    """迁移执行请求体。"""
    reason: str
    match_key_prefix: str = ""
    skip_gate_check: bool = False


@router.get("/gate")
async def cost_catalog_gate(
    active_only: bool = Query(True, description="只统计 active=True 的行"),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """M4 成本库启动门槛评估。

    双门槛（缺一不可）：
    - 覆盖率 ≥ 80%（material_dict_id 非空占比）
    - 异常率 < 10%（anomaly_flag == 'error' 占比）
    """
    result = cost_catalog_service.get_gate_status(db, active_only=active_only)
    return result


@router.get("/list")
async def cost_catalog_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    keyword: str = Query(""),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """成本库列表查询（只读派生缓存）。"""
    result = cost_migration_service.list_cost_catalog(
        db, page=page, per_page=per_page, keyword=keyword,
    )
    return {"success": True, "data": result}


@router.get("/migrate/preview")
async def migrate_preview(
    match_key_prefix: str = Query(""),
    user=Depends(require_role(ROLE_ESTIMATOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """迁移预览（不写库）。返回将迁移的 match_key 列表及统计摘要。"""
    result = cost_migration_service.preview_migration(db, match_key_prefix=match_key_prefix)
    return {"success": True, "data": result}


@router.post("/migrate/execute")
async def migrate_execute(
    req: MigrationExecuteRequest,
    user=Depends(require_role(ROLE_ESTIMATOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """执行迁移：boq_item → cost_catalog upsert。

    - 默认检查 M3.6 门槛，未达标拒绝迁移
    - skip_gate_check=True 可强制迁移（需 admin 角色，前端应二次确认）
    - reason 必填（写审计日志）
    """
    # 强制跳过门槛需 admin
    if req.skip_gate_check and user.get("role") != ROLE_ADMIN:
        return {"success": False, "error": "forbidden", "message": "仅 admin 可跳过门槛检查强制迁移"}

    operator = user.get("username", "unknown")
    result = cost_migration_service.execute_migration(
        db,
        operator=operator,
        reason=req.reason,
        match_key_prefix=req.match_key_prefix,
        skip_gate_check=req.skip_gate_check,
    )
    return result
