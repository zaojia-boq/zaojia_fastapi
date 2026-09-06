# -*- coding: utf-8 -*-
"""页面路由层 —— 渲染 9 个业务页面模板。

设计原则：
  - 复用 Odoo 版 nav_items.js 的导航结构（4 组 8 项），badge 由真实计数驱动
  - 每个页面调用 page_services 获取数据，模板用 Jinja 循环渲染（非硬编码）
  - **会话由 Depends(get_db) 注入**：测试期被 conftest 覆盖为内存库，
    生产期走连接池；服务层不再自建连接，消除泄漏与方言耦合
  - **autoescape 常开**：所有反射型参数（搜索词等）自动转义，防 XSS
  - 渲染异常不抛出 500，统一渲染 error.html

安全（M2.6.1 / P0-2 页面鉴权）：
  - 所有页面路由加 Depends(get_page_user)，未带令牌 → 401
  - 导入 / 批次 / 设置 三个写操作页加 require_page_admin（admin 角色）
  - 开发期提供 /login?token= 写入 zj_token Cookie，浏览器一次认证全站
  - 鉴权逻辑复用 app.core.security 的 dev_token 校验，OA SSO 对接后整体替换
  - 不改动 security.py（维持泳道边界），仅在本文件内实现 cookie+header 双通道
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
from app.core.security import settings as sec_settings, ROLE_ADMIN

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


async def get_page_user(request: Request) -> dict:
    """HTML 页面鉴权依赖。

    - 优先取 Authorization: Bearer 头（API/脚本调用）
    - 回退取 zj_token Cookie（浏览器导航 GET，无法自动带 Bearer 头）
    - 开发期校验 settings.dev_token，返回固定 admin
    - 生产期（OA SSO 未对接）拒绝一切访问（fail-closed）

    注：逻辑与 app.core.security.get_current_user 的 dev 分支保持一致，
    但额外支持 Cookie，便于浏览器整站导航认证；OA SSO 对接后此处一并替换。
    """
    creds: HTTPAuthorizationCredentials | None = await _page_bearer(request)
    token = creds.credentials if creds else None
    if not token:
        token = request.cookies.get("zj_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录：缺少访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if sec_settings.env == "development":
        if not sec_settings.dev_token or token != sec_settings.dev_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="令牌无效",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 与 security.get_current_user 一致：写入 state 供 AuditMiddleware 落审计
        request.state.username = "dev_admin"
        return {"username": "dev_admin", "role": ROLE_ADMIN}

    # 生产期：OA SSO 未对接前拒绝（fail-closed）
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="认证服务未就绪：OA SSO 对接完成前禁止生产环境访问",
    )


async def require_page_admin(user: dict = Depends(get_page_user)) -> dict:
    """页面 admin 角色依赖（写操作页：导入 / 批次 / 设置）。

    必须是「直接依赖函数 + 子依赖」形式，不能写成
    ``def require_page_admin(): return checker`` 工厂——FastAPI 会把工厂的
    返回值（checker 函数本身）直接注入为 user，而不会再解析其内部的
    ``Depends(get_page_user)``，导致鉴权被完全绕过（P0 安全漏洞）。
    """
    if user.get("role") != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"需要角色: {ROLE_ADMIN}",
        )
    return user


def _render(name: str, context: dict) -> HTMLResponse:
    """渲染模板；异常时降级到 error.html，不泄漏堆栈。"""
    try:
        html = _env.get_template(name).render(context)
        return HTMLResponse(content=html)
    except Exception as exc:  # noqa: BLE001 —— 页面层兜底，避免 500 白屏
        logger.exception("页面渲染失败: %s", name)
        try:
            html = _env.get_template("error.html").render({
                "request": context.get("request"),
                "active": context.get("active", ""),
                "title": "页面错误",
                "nav_groups": svc.NAV_GROUPS,
                "nav_badges": {},
                "message": f"页面「{context.get('title', name)}」渲染失败：{type(exc).__name__}",
                "detail": str(exc),
            })
            return HTMLResponse(content=html, status_code=500)
        except Exception:  # noqa: BLE001
            return HTMLResponse(content="<h1>500 页面渲染失败</h1>", status_code=500)


def _ctx(request: Request, db: Session, active: str, title: str,
         user: dict | None = None, **extra) -> dict:
    """公共上下文：导航 + 动态 badge + 演示数据标记 + 当前用户。"""
    ctx = {
        "request": request,
        "active": active,
        "title": title,
        "nav_groups": svc.NAV_GROUPS,
        "nav_badges": svc.get_nav_badges(db),
        "is_demo": svc.USE_MOCK_DATA,
        "user": user or {"username": "dev_admin", "role": ROLE_ADMIN},
    }
    ctx.update(extra)
    return ctx


# ============================================================================
# 开发期认证路由（仅 development 生效）
# ============================================================================

@router.get("/login", include_in_schema=False)
async def dev_login(token: str = "", next: str = "/"):
    """开发期登录：写入 zj_token Cookie，浏览器一次认证全站。生产期 404。

    用法：/login?token=<DEV_TOKEN>&next=/dashboard
    """
    if sec_settings.env != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    safe_next = next or "/"
    # 防开放重定向：仅允许站内相对路径
    if safe_next.startswith("http://") or safe_next.startswith("https://") \
            or safe_next.startswith("//"):
        safe_next = "/"
    resp = RedirectResponse(url=safe_next, status_code=303)
    if token:
        resp.set_cookie(
            "zj_token", token,
            # 开发期 httponly=False：app.js 的 getToken() 需从 cookie 读 token 放到
            # Authorization: Bearer 头（API 路由的 get_current_user 仅认 Bearer 头）。
            # TODO（OA SSO 对接后必须修复）：改为 httponly=True + samesite="strict" +
            # secure=True，并让 API 路由同时支持 cookie 鉴权（credentials: include），
            # 彻底消除 XSS 窃令牌风险。当前为开发期已知技术债务。
            httponly=False,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )
    return resp


@router.get("/logout", include_in_schema=False)
async def dev_logout(next: str = "/"):
    """开发期登出：清除 zj_token Cookie。"""
    safe_next = next or "/"
    resp = RedirectResponse(url=safe_next, status_code=303)
    resp.delete_cookie("zj_token")
    return resp


# ============================================================================
# 页面路由
# ============================================================================

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root(request: Request, db: Session = Depends(get_db),
              user: dict = Depends(get_page_user)):
    """根路径 = 数据概览（与 /dashboard 同一模板，避免重复实现）。"""
    return await dashboard_page(request, db, user)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db),
                         user: dict = Depends(get_page_user)):
    """数据概览 —— 对标 dashboard.js。"""
    data = svc.get_dashboard_data(db)
    return _render("dashboard.html", _ctx(request, db, "dash", "数据概览", user, **data))


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, db: Session = Depends(get_db),
                      user: dict = Depends(get_page_user)):
    """清单检索 —— 对标 boq.js。查询参数全量透传并回显。"""
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
    )
    return _render("search.html", _ctx(
        request, db, "boq", "清单检索", user,
        major_options=svc.MAJOR_DEFS,
        source_options=[{"id": k, "label": v} for k, v in svc.DATA_SOURCE_TYPES.items()],
        params={"kw": kw, "major": f_major, "code": f_code, "name": f_name,
                "source": f_source, "anomaly": f_anomaly, "status": std_status},
        **data,
    ))


@router.get("/price", response_class=HTMLResponse)
async def price_page(request: Request, db: Session = Depends(get_db),
                     user: dict = Depends(get_page_user)):
    """单价分析 —— 对标 price.js。默认口径仅「已完工程」。"""
    qp = request.query_params
    try:
        range_months = int(qp.get("range", 24))
    except ValueError:
        range_months = 24
    if range_months not in (6, 12, 24, 36):
        range_months = 24
    major = qp.get("major", "all")

    data = svc.get_price_analysis(db, range_months=range_months, major=major)
    return _render("price.html", _ctx(
        request, db, "price", "单价分析", user,
        range_options=[{"month": m, "label": f"近 {m} 月"} for m in (6, 12, 24, 36)],
        major_options=[{"prefix": "all", "label": "全部专业"}] + [
            {"prefix": m["prefix"], "label": m["name"]} for m in svc.MAJOR_DEFS
        ],
        current_range=range_months,
        current_major=major,
        **data,
    ))


@router.get("/import", response_class=HTMLResponse)
async def import_wizard_page(request: Request, db: Session = Depends(get_db),
                             user: dict = Depends(require_page_admin)):
    """导入向导 —— 对标 import.js。admin 专属。"""
    batches = svc.get_recent_batches(db, limit=5)
    return _render("import_wizard.html", _ctx(
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


@router.get("/batches", response_class=HTMLResponse)
async def batches_page(request: Request, db: Session = Depends(get_db),
                       user: dict = Depends(require_page_admin)):
    """批次管理 —— 对标 batch.js。admin 专属。"""
    data = svc.list_batches(db)
    return _render("batches.html", _ctx(request, db, "batch", "批次管理", user, **data))


@router.get("/dict", response_class=HTMLResponse)
async def material_dict_page(request: Request, db: Session = Depends(get_db),
                             user: dict = Depends(get_page_user)):
    """物料字典 —— 对标 dict.js。支持 ?sel=<id> 选中节点。"""
    try:
        sel = int(request.query_params.get("sel"))
    except (TypeError, ValueError):
        sel = None
    data = svc.get_material_dict_tree(db, selected=sel)
    return _render("material_dict.html", _ctx(request, db, "dict", "物料字典", user, **data))


@router.get("/match", response_class=HTMLResponse)
async def match_confirm_page(request: Request, db: Session = Depends(get_db),
                             user: dict = Depends(get_page_user)):
    """匹配确认 —— 对标 match.js。候选由 data.match_score 确定性打分。"""
    data = svc.get_pending_matches(db)
    return _render("match_confirm.html", _ctx(
        request, db, "match", "匹配确认", user,
        filter_options=[
            {"id": "all", "label": "全部"},
            {"id": "high", "label": "高置信（≥90）"},
            {"id": "low", "label": "低置信（<75）"},
        ],
        # 阈值与 data.match_score / 设置页同源
        thresholds={"auto": 98.0, "cand": 75.0},
        **data,
    ))


@router.get("/quality", response_class=HTMLResponse)
async def quality_page(request: Request, db: Session = Depends(get_db),
                       user: dict = Depends(get_page_user)):
    """数据质量 —— 对标 quality.js。"""
    data = svc.get_quality_dashboard(db)
    return _render("quality.html", _ctx(
        request, db, "quality", "数据质量", user,
        source_labels=svc.DATA_SOURCE_TYPES,
        **data,
    ))


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db),
                        user: dict = Depends(require_page_admin)):
    """系统设置 —— 对标 setting.js。admin 专属。"""
    data = svc.get_settings()
    return _render("settings.html", _ctx(request, db, "setting", "系统设置", user, **data))
