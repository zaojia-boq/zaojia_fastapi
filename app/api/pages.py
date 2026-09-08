# -*- coding: utf-8 -*-
"""页面路由层 —— 方案 A：单应用 + 路由前缀分离。

路由划分：
- /portal/*  前端展示页（dashboard/search/price），可选登录，未登录可只读
- /admin/*   后端管理页（dashboard/import/batches/dict/match/quality/settings），必须登录+角色
- /login /logout  开发期认证（写入 zj_token + zj_role Cookie）
- /          首页重定向到 /portal/dashboard
- 旧路由（/dashboard /search 等）做 301 重定向到新前缀

三用户角色：
- admin      管理员：全部权限
- estimator  造价工程师：查询 + 匹配确认 + 字典维护 + 批次查看
- viewer     只读用户：查询 + 导出（Portal 页），无 Admin 页权限

开发期角色指定：/login?token=<DEV_TOKEN>&role=<admin|estimator|viewer>
生产期（OA SSO 对接后）：按 OA 用户部门/职位自动映射角色。
"""
import logging
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import page_services as svc
from app.core.security import settings as sec_settings, ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER
from data.match_score import HIGH_CONF_SCORE

router = APIRouter()
logger = logging.getLogger(__name__)

# autoescape 常开：任何注入模板的变量（含查询参数回显）都会被转义
_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
    cache_size=0,
)

# 页面鉴权：cookie + header 双通道（开发期友好）
_page_bearer = HTTPBearer(auto_error=False)

# 角色权限矩阵：哪些角色可以访问 Admin 页
ADMIN_ACCESS_ROLES = {ROLE_ADMIN, ROLE_ESTIMATOR}
ADMIN_WRITE_ROLES = {ROLE_ADMIN}  # 导入/删除/设置等写操作仅 admin


# ============================================================================
# 鉴权依赖（三用户角色）
# ============================================================================

async def get_page_user_optional(request: Request) -> dict | None:
    """Portal 页可选登录：未登录返回 None，已登录返回用户信息。

    开发期：校验 zj_token Cookie 或 Authorization Bearer 头 == dev_token，
    角色从 zj_role Cookie 读取（默认 admin，保持向后兼容）。
    """
    creds: HTTPAuthorizationCredentials | None = await _page_bearer(request)
    token = creds.credentials if creds else None
    if not token:
        token = request.cookies.get("zj_token")

    if not token:
        return None  # 未登录

    if sec_settings.env == "development":
        if not sec_settings.dev_token or token != sec_settings.dev_token:
            return None  # token 无效，视为未登录
        # 角色从 zj_role Cookie 读取，默认 admin
        role = request.cookies.get("zj_role", ROLE_ADMIN)
        if role not in (ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER):
            role = ROLE_ADMIN
        username = f"dev_{role}"
        request.state.username = username
        request.state.user_role = role
        return {"username": username, "role": role}

    # 生产期：OA SSO 未对接前拒绝（fail-closed）
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="认证服务未就绪：OA SSO 对接完成前禁止生产环境访问",
    )


async def get_page_user(request: Request) -> dict:
    """Admin 页必须登录：未登录 401。"""
    user = await get_page_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录：缺少访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin_role(user: dict = Depends(get_page_user)) -> dict:
    """Admin 写操作页（导入/批次/设置）：必须 admin 角色。"""
    if user.get("role") not in ADMIN_WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"需要角色: {ROLE_ADMIN}（当前: {user.get('role')}）",
        )
    return user


async def require_admin_access(user: dict = Depends(get_page_user)) -> dict:
    """Admin 普通页（字典/匹配/质量）：admin 或 estimator 角色。"""
    if user.get("role") not in ADMIN_ACCESS_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"需要角色: {ROLE_ADMIN} 或 {ROLE_ESTIMATOR}（当前: {user.get('role')}）",
        )
    return user


# ============================================================================
# 导航配置（Portal 简洁3项 / Admin 完整8项）
# ============================================================================

PORTAL_NAV_GROUPS = [
    {
        "label": "数据查询",
        "items": [
            {"id": "dash", "label": "数据概览", "path": "/portal/dashboard", "icon": "◈", "badge_key": None},
            {"id": "boq", "label": "清单检索", "path": "/portal/search", "icon": "▤", "badge_key": None},
            {"id": "price", "label": "价格分析", "path": "/portal/price", "icon": "◑", "badge_key": None},
        ],
    },
]

ADMIN_NAV_GROUPS = [
    {
        "label": "数据管理",
        "items": [
            {"id": "dash", "label": "管理概览", "path": "/admin/dashboard", "icon": "◈", "badge_key": None},
            {"id": "import", "label": "导入向导", "path": "/admin/import", "icon": "⇪", "badge_key": None},
            {"id": "batch", "label": "批次管理", "path": "/admin/batches", "icon": "▷", "badge_key": None},
        ],
    },
    {
        "label": "标准化",
        "items": [
            {"id": "dict", "label": "物料字典", "path": "/admin/dict", "icon": "☰", "badge_key": None},
            {"id": "match", "label": "匹配确认", "path": "/admin/match", "icon": "≋", "badge_key": "pending_match"},
        ],
    },
    {
        "label": "质量与设置",
        "items": [
            {"id": "quality", "label": "数据质量", "path": "/admin/quality", "icon": "◍", "badge_key": None},
            {"id": "setting", "label": "系统设置", "path": "/admin/settings", "icon": "⚙", "badge_key": None},
        ],
    },
]


# ============================================================================
# 渲染辅助
# ============================================================================

def _render(name: str, context: dict) -> HTMLResponse:
    """渲染模板；异常时降级到 error.html，不泄漏堆栈。"""
    try:
        html = _env.get_template(name).render(context)
        return HTMLResponse(content=html)
    except Exception as exc:  # noqa: BLE001
        logger.exception("页面渲染失败: %s", name)
        try:
            html = _env.get_template("error.html").render({
                "request": context.get("request"),
                "active": context.get("active", ""),
                "title": "页面错误",
                "nav_groups": context.get("nav_groups", ADMIN_NAV_GROUPS),
                "nav_badges": {},
                "message": f"页面「{context.get('title', name)}」渲染失败：{type(exc).__name__}",
                "detail": str(exc),
            })
            return HTMLResponse(content=html, status_code=500)
        except Exception:  # noqa: BLE001
            return HTMLResponse(content="<h1>500 页面渲染失败</h1>", status_code=500)


def _ctx_portal(request: Request, db: Session, active: str, title: str,
                user: dict | None = None, **extra) -> dict:
    """Portal 页公共上下文：Portal 导航 + 可选用户。"""
    ctx = {
        "request": request,
        "active": active,
        "title": title,
        "nav_groups": PORTAL_NAV_GROUPS,
        "nav_badges": {},
        "is_demo": svc.USE_MOCK_DATA,
        "user": user,  # Portal 页 user 可能为 None（未登录）
        "is_portal": True,
    }
    ctx.update(extra)
    return ctx


def _ctx_admin(request: Request, db: Session, active: str, title: str,
               user: dict, **extra) -> dict:
    """Admin 页公共上下文：Admin 导航 + 动态 badge + 必选用户。"""
    ctx = {
        "request": request,
        "active": active,
        "title": title,
        "nav_groups": ADMIN_NAV_GROUPS,
        "nav_badges": svc.get_nav_badges(db),
        "is_demo": svc.USE_MOCK_DATA,
        "user": user,
        "is_admin": True,
    }
    ctx.update(extra)
    return ctx


# ============================================================================
# 开发期认证路由（仅 development 生效）
# ============================================================================

@router.get("/login", include_in_schema=False)
async def dev_login(token: str = "", role: str = ROLE_ADMIN, next: str = "/portal/dashboard"):
    """开发期登录：写入 zj_token + zj_role Cookie，浏览器一次认证全站。

    用法：/login?token=<DEV_TOKEN>&role=<admin|estimator|viewer>&next=/portal/dashboard
    生产期 404。
    """
    if sec_settings.env != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    safe_next = next or "/portal/dashboard"
    # 防开放重定向：仅允许站内相对路径
    if safe_next.startswith("http://") or safe_next.startswith("https://") \
            or safe_next.startswith("//"):
        safe_next = "/portal/dashboard"
    resp = RedirectResponse(url=safe_next, status_code=303)
    if token:
        # zj_token 设置 httponly=True 防 XSS 窃取（security.py 已支持 Cookie 认证）
        # 开发期 samesite=lax，生产期应设 secure=True（需 HTTPS）
        resp.set_cookie("zj_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
        # zj_role 保持 httponly=False（前端需要读取角色来控制 UI 显示）
        if role not in (ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER):
            role = ROLE_ADMIN
        resp.set_cookie("zj_role", role, httponly=False, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@router.get("/logout", include_in_schema=False)
async def dev_logout(next: str = "/portal/dashboard"):
    """开发期登出：清除 zj_token + zj_role Cookie。"""
    safe_next = next or "/portal/dashboard"
    resp = RedirectResponse(url=safe_next, status_code=303)
    resp.delete_cookie("zj_token")
    resp.delete_cookie("zj_role")
    return resp


# ============================================================================
# 旧路由重定向（301 到新前缀）
# ============================================================================
@router.get("/dashboard", include_in_schema=False)
async def old_dashboard():
    return RedirectResponse(url="/portal/dashboard", status_code=301)


@router.get("/search", include_in_schema=False)
async def old_search():
    return RedirectResponse(url="/portal/search", status_code=301)


@router.get("/price", include_in_schema=False)
async def old_price():
    return RedirectResponse(url="/portal/price", status_code=301)


@router.get("/import", include_in_schema=False)
async def old_import():
    return RedirectResponse(url="/admin/import", status_code=301)


@router.get("/batches", include_in_schema=False)
async def old_batches():
    return RedirectResponse(url="/admin/batches", status_code=301)


@router.get("/dict", include_in_schema=False)
async def old_dict():
    return RedirectResponse(url="/admin/dict", status_code=301)


@router.get("/match", include_in_schema=False)
async def old_match():
    return RedirectResponse(url="/admin/match", status_code=301)


@router.get("/quality", include_in_schema=False)
async def old_quality():
    return RedirectResponse(url="/admin/quality", status_code=301)


@router.get("/settings", include_in_schema=False)
async def old_settings():
    return RedirectResponse(url="/admin/settings", status_code=301)


# ============================================================================
# Portal 前端展示页（/portal/*，可选登录）
# ============================================================================

@router.get("/portal/dashboard", response_class=HTMLResponse)
async def portal_dashboard(request: Request, db: Session = Depends(get_db),
                           user: dict | None = Depends(get_page_user_optional)):
    """Portal 数据概览 —— 未登录可访问（只读，仅已标准化数据）。"""
    data = svc.get_dashboard_data(db, only_std=(user is None))
    return _render("portal/dashboard.html", _ctx_portal(request, db, "dash", "数据概览", user, **data))


@router.get("/portal/search", response_class=HTMLResponse)
async def portal_search(request: Request, db: Session = Depends(get_db),
                        user: dict | None = Depends(get_page_user_optional)):
    """Portal 清单检索 —— 未登录可访问（只读）。"""
    qp = request.query_params
    kw = qp.get("kw", "")
    f_major = qp.get("major", "")
    f_code = qp.get("code", "")
    f_name = qp.get("name", "")
    f_source = qp.get("source", "")
    f_anomaly = qp.get("anomaly", "")
    std_status = qp.get("status", "")
    try:
        page = max(1, int(qp.get("page", 1)))
    except ValueError:
        page = 1

    data = svc.search_boq_items(
        db, kw=kw, f_major=f_major, f_code=f_code, f_name=f_name,
        f_source=f_source, f_anomaly=f_anomaly, std_status=std_status, page=page,
        only_std=(user is None),  # 未登录用户仅能看到已标准化数据
    )
    return _render("portal/search.html", _ctx_portal(
        request, db, "boq", "清单检索", user,
        major_options=svc.MAJOR_DEFS,
        source_options=[{"id": k, "label": v} for k, v in svc.DATA_SOURCE_TYPES.items()],
        params={"kw": kw, "major": f_major, "code": f_code, "name": f_name,
                "source": f_source, "anomaly": f_anomaly, "status": std_status},
        **data,
    ))


@router.get("/portal/price", response_class=HTMLResponse)
async def portal_price(request: Request, db: Session = Depends(get_db),
                       user: dict | None = Depends(get_page_user_optional)):
    """Portal 价格分析 —— 未登录可访问（只读）。"""
    qp = request.query_params
    try:
        range_months = int(qp.get("range", 24))
    except ValueError:
        range_months = 24
    if range_months not in (6, 12, 24, 36):
        range_months = 24
    major = qp.get("major", "all")

    data = svc.get_price_analysis(db, range_months=range_months, major=major)
    return _render("portal/price.html", _ctx_portal(
        request, db, "price", "价格分析", user,
        range_options=[{"month": m, "label": f"近 {m} 月"} for m in (6, 12, 24, 36)],
        major_options=[{"prefix": "all", "label": "全部专业"}] + [
            {"prefix": m["prefix"], "label": m["name"]} for m in svc.MAJOR_DEFS
        ],
        current_range=range_months,
        current_major=major,
        **data,
    ))


# ============================================================================
# Admin 后端管理页（/admin/*，必须登录+角色）
# ============================================================================

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db),
                          user: dict = Depends(require_admin_access)):
    """Admin 管理概览 —— admin/estimator 可访问。"""
    data = svc.get_dashboard_data(db)
    return _render("admin/dashboard.html", _ctx_admin(request, db, "dash", "管理概览", user, **data))


@router.get("/admin/import", response_class=HTMLResponse)
async def admin_import(request: Request, db: Session = Depends(get_db),
                       user: dict = Depends(require_admin_role)):
    """Admin 导入向导 —— 仅 admin。"""
    batches = svc.get_recent_batches(db, limit=5)
    return _render("admin/import_wizard.html", _ctx_admin(
        request, db, "import", "导入向导", user,
        batches=batches,
        step_defs=[
            {"key": "upload", "label": "1 选择文件"},
            {"key": "source", "label": "2 数据来源"},
            {"key": "mapping", "label": "3 字段映射"},
            {"key": "preview", "label": "4 预览校验"},
            {"key": "confirm", "label": "5 确认入库"},
        ],
        source_defs=[
            {"value": "completed", "label": "已完工程", "desc": "计入历史均价统计"},
            {"value": "control_price", "label": "招标控制价", "desc": "基准价，不进入均价统计"},
            {"value": "bid_price", "label": "投标报价", "desc": "参考用，不进入均价统计"},
            {"value": "pending_review", "label": "待审清单", "desc": "不计入历史均价，需复核后放行"},
            {"value": "info_price", "label": "信息价", "desc": "参考价，不进入均价统计"},
        ],
        dev_token_placeholder=sec_settings.dev_token or "",
    ))


@router.get("/admin/batches", response_class=HTMLResponse)
async def admin_batches(request: Request, db: Session = Depends(get_db),
                        user: dict = Depends(require_admin_role)):
    """Admin 批次管理 —— 仅 admin。"""
    data = svc.list_batches(db)
    return _render("admin/batches.html", _ctx_admin(request, db, "batch", "批次管理", user, **data))


@router.get("/admin/batches/{batch_id}", response_class=HTMLResponse)
async def admin_batch_detail(request: Request, batch_id: int, db: Session = Depends(get_db),
                              user: dict = Depends(require_admin_role)):
    """Admin 批次详情 —— 仅 admin。"""
    data = svc.get_batch_detail(batch_id, db)
    return _render("admin/batch_detail.html", _ctx_admin(request, db, "batch", "批次详情", user, **data))


@router.get("/admin/dict", response_class=HTMLResponse)
async def admin_dict(request: Request, db: Session = Depends(get_db),
                     user: dict = Depends(require_admin_access)):
    """Admin 物料字典 —— admin/estimator 可访问。"""
    try:
        sel = int(request.query_params.get("sel"))
    except (TypeError, ValueError):
        sel = None
    data = svc.get_material_dict_tree(db, selected=sel)
    return _render("admin/material_dict.html", _ctx_admin(request, db, "dict", "物料字典", user, **data))


@router.get("/admin/match", response_class=HTMLResponse)
async def admin_match(request: Request, db: Session = Depends(get_db),
                      user: dict = Depends(require_admin_access)):
    """Admin 匹配确认 —— admin/estimator 可访问。"""
    data = svc.get_pending_matches(db)
    return _render("admin/match_confirm.html", _ctx_admin(
        request, db, "match", "匹配确认", user,
        filter_options=[
            {"id": "all", "label": "全部"},
            {"id": "high", "label": "高置信（≥90）"},
            {"id": "low", "label": "低置信（<75）"},
        ],
        thresholds={"auto": HIGH_CONF_SCORE, "cand": 75.0},
        **data,
    ))


@router.get("/admin/quality", response_class=HTMLResponse)
async def admin_quality(request: Request, db: Session = Depends(get_db),
                        user: dict = Depends(require_admin_access)):
    """Admin 数据质量 —— admin/estimator 可访问。"""
    data = svc.get_quality_dashboard(db)
    return _render("admin/quality.html", _ctx_admin(
        request, db, "quality", "数据质量", user,
        source_labels=svc.DATA_SOURCE_TYPES,
        **data,
    ))


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, db: Session = Depends(get_db),
                         user: dict = Depends(require_admin_role)):
    """Admin 系统设置 —— 仅 admin。"""
    data = svc.get_settings()
    return _render("admin/settings.html", _ctx_admin(request, db, "setting", "系统设置", user, **data))
