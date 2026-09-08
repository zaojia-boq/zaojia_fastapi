# -*- coding: utf-8 -*-
"""认证与授权。

v1.1 安全加固（2026-09-05 代码审查后）：
- 从 fail-open 改为 fail-closed：无 token 401，token 不匹配 401
- 开发期用固定 dev_token（从 env 读取），不再是"任意 Authorization 头即 admin"
- OA SSO 对接到位后替换 get_current_user 为 OA token 校验

v1.2（2026-09-06 审查修复 P1-1）：
- 鉴权通过时写入 request.state.username，供 AuditMiddleware 读取真实操作者
- 修复前中间件 operator 恒为 anonymous，审计四元组之「谁」失效

铁律：本服务在 OA SSO 对接完成前，严禁暴露到任何非可信网络。
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings

security = HTTPBearer(auto_error=False)

# 角色定义（与 Odoo 版权限三组对齐）
ROLE_ADMIN = "admin"        # 导入/删除/标注/用户管理
ROLE_ESTIMATOR = "estimator"  # 查询/导出/单价分析，B类字段只读
ROLE_VIEWER = "viewer"      # 只读浏览，禁导出


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """当前用户。fail-closed：无 token 或 token 不匹配均 401。

    开发期（env=development）：校验 Bearer token == settings.dev_token。
    生产期（env=production）：OA SSO 对接后，此处校验 OA token 并映射角色。

    鉴权通过时写入 request.state.username（供 AuditMiddleware 读取）。

    支持两种认证方式（按优先级）：
    1. Authorization: Bearer <token> 头（API 调用）
    2. zj_token Cookie（页面浏览，httponly=True 防 XSS 窃取）

    TODO: 对接易达 ECMS SSO 后，替换为 OA token 校验 + 角色映射。
    """
    # 优先从 Authorization 头获取 token
    token = None
    if credentials:
        token = credentials.credentials
    # 回退：从 Cookie 获取（页面浏览场景）
    if not token:
        token = request.cookies.get("zj_token")

    # fail-closed：无 token → 401
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录：缺少 Authorization 头或 Cookie",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 开发期：校验固定 dev_token
    if settings.env == "development":
        if not settings.dev_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="开发环境未配置 DEV_TOKEN，请在 .env 中设置",
            )
        if token != settings.dev_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 无效",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 开发期固定返回 admin（OA 对接后按 OA 用户映射角色）
        user = {"username": "dev_admin", "role": ROLE_ADMIN}
        # 写入 request.state，供审计中间件读取真实操作者
        request.state.username = user["username"]
        request.state.user_role = user["role"]
        return user

    # 生产期：OA SSO 未对接前拒绝一切访问（fail-closed）
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="认证服务未就绪：OA SSO 对接完成前禁止生产环境访问",
    )


def require_role(*roles):
    """角色检查依赖工厂。"""
    async def checker(request: Request, user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要角色: {', '.join(roles)}",
            )
        return user
    return checker
