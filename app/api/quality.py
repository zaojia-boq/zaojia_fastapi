# -*- coding: utf-8 -*-
"""M3.2 数据质量仪表盘 API。

路由：
- GET /api/quality/dashboard —— 四环指标（覆盖率/匹配质量/性质分布/异常率）+ 达标门

权限：三角色均可查询（只读视图）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user
from app.services import data_quality_service

router = APIRouter(prefix="/api/quality", tags=["数据质量"])


@router.get("/dashboard")
async def quality_dashboard(
    active_only: bool = Query(True, description="只统计 active=True 的行"),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """数据质量仪表盘（四环指标 + 达标门）。

    四环指标：
    - coverage: material_dict_id 非空占比
    - match_key_quality: match_key_source ∈ {dict, std} 占比
    - data_source_dist: 按 data_source_type 计数分布
    - anomaly_rate: anomaly_flag == 'error' 占比

    达标门：
    - m3_pass: coverage >= 0.70 AND anomaly_rate < 0.15
    - m4_pass: coverage >= 0.80 AND anomaly_rate < 0.10（M4 成本库迁移门槛）
    """
    result = data_quality_service.get_dashboard(db, active_only=active_only)
    return result
