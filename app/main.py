# -*- coding: utf-8 -*-
"""造价数据门户 —— FastAPI 入口。

阶段1（当前）：独立账号 + 健康检查 + 纯函数验证 + 前端页面。
阶段2：对接易达 ECMS OA SSO，替换认证层。
"""
import os
import warnings

# 过滤 jieba 内部的 SyntaxWarning（invalid escape sequence），不影响功能
warnings.filterwarnings("ignore", category=SyntaxWarning, module="jieba")

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.config import settings
from app.core.security import get_current_user, require_role, ROLE_ADMIN
from app.core.audit import audit_log, AuditMiddleware

app = FastAPI(
    title=settings.app_name,
    description="工程造价数据库 —— 多省多批次清单导入、标准化、聚合分析、单价分析",
    version="0.4.0",
    # 生产环境禁用 API 文档（安全加固：避免接口结构泄漏）
    docs_url="/docs" if settings.env == "development" else None,
    redoc_url="/redoc" if settings.env == "development" else None,
    openapi_url="/openapi.json" if settings.env == "development" else None,
)

# 审计中间件（所有写操作落审计日志）
app.add_middleware(AuditMiddleware)

# 静态文件
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ------------------------------------------------------------------
# 系统路由
# ------------------------------------------------------------------

@app.get("/", tags=["系统"])
async def root():
    """根路径跳转到 Portal 数据概览页（方案 A：路由前缀分离）。"""
    return RedirectResponse(url="/portal/dashboard", status_code=301)


@app.get("/health", tags=["系统"])
async def health():
    """健康检查。"""
    return {"status": "ok", "app": settings.app_name, "version": "0.4.0"}


@app.get("/api/me", tags=["认证"])
async def me(user=Depends(get_current_user)):
    """当前用户信息。"""
    return user


@app.get("/api/public/hello", tags=["公开"])
async def public_hello():
    """公开接口（无需登录），用于验证服务启动。"""
    return {"message": "造价数据门户已启动", "oa_sso": settings.oa_sso_enabled}


@app.post("/api/admin/audit-test", tags=["管理"])
async def audit_test(user=Depends(require_role(ROLE_ADMIN))):
    """管理员测试：写一条审计日志。"""
    entry = audit_log(operator=user["username"], action="audit_test", reason="接口测试")
    return {"ok": True, "audit": entry}


# ------------------------------------------------------------------
# API 路由（M2-M4）
# ------------------------------------------------------------------
from app.api.import_api import router as import_router
from app.api.query import router as query_router
from app.api.batch import router as batch_router
from app.api.price import router as price_router
from app.api.match import router as match_router
from app.api.quality import router as quality_router
from app.api.batch_operation import router as batch_op_router
from app.api.cost_catalog import router as cost_catalog_router
from app.api.dict import router as dict_router
from app.api.favorite import router as favorite_router
from app.api.tag import router as tag_router

app.include_router(import_router)
app.include_router(query_router)
app.include_router(batch_router)
app.include_router(price_router)
app.include_router(match_router)
app.include_router(quality_router)
app.include_router(batch_op_router)
app.include_router(cost_catalog_router)
app.include_router(dict_router)
app.include_router(favorite_router)
app.include_router(tag_router)

# ------------------------------------------------------------------
# 页面路由（M2.5 / M2.6）
# ------------------------------------------------------------------
from app.api.pages import router as pages_router
app.include_router(pages_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8777, reload=True)
