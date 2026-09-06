# -*- coding: utf-8 -*-
"""M3.1 单价分析 API。

路由：
- GET /api/price/kpis —— KPI 卡片数据（样本数/均价/区间/异常数）
- GET /api/price/analysis —— 四维度分组分析（aggregate_id/match_key_source/province/price_period）

权限：三角色均可查询（单价分析是只读视图）。
默认域：data_source_type=completed + unit_rate_num 非空（M3 §3.2 唯一出处）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.core.security import get_current_user
from app.services import price_service

router = APIRouter(prefix="/api/price", tags=["单价分析"])


@router.get("/kpis")
async def price_kpis(
    province: str = Query(None, description="按省份过滤"),
    price_period: str = Query(None, description="按价格期过滤（YYYY-MM）"),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """KPI 卡片数据（样本数/均价/最低/最高/异常数）。

    默认域：completed + unit_rate_num 非空。
    异常判定：相对本批均值偏离 >30% 且样本数 >=3（M3 §3.4，只读展示不写回）。
    """
    domain = []
    if province:
        domain.append(('province', '=', province))
    if price_period:
        # price_period 存当月 1 日，按月份前缀过滤
        domain.append(('price_period', 'like', f'{price_period}%'))

    result = price_service.get_kpis(db, domain=domain if domain else None)
    return result


@router.get("/analysis")
async def price_analysis(
    province: str = Query(None, description="按省份过滤"),
    price_period: str = Query(None, description="按价格期过滤（YYYY-MM）"),
    threshold: float = Query(0.30, ge=0.1, le=0.5, description="异常阈值（默认 30%）"),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """四维度分组分析（透视表数据）。

    维度：aggregate_id / match_key_source / province / price_period（M3 §3.3）。
    每组返回：group / avg / min / max / count / anomaly_count。
    """
    domain = []
    if province:
        domain.append(('province', '=', province))
    if price_period:
        domain.append(('price_period', 'like', f'{price_period}%'))

    result = price_service.get_analysis(db, domain=domain if domain else None, threshold=threshold)
    return result
