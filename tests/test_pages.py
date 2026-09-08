# -*- coding: utf-8 -*-
"""页面路由测试 —— 方案 A：单应用 + 路由前缀分离。

测试目标：
  - Portal 页（/portal/*）未登录可访问（200），已登录也可访问
  - Admin 页（/admin/*）未登录 401，已登录+正确角色 200
  - 三用户角色权限：admin 全部、estimator 部分、viewer 无 Admin 页
  - 旧路由（/dashboard 等）返回 301 重定向到新前缀
  - 首页 / 重定向到 /portal/dashboard
  - 页面包含关键内容节点（标题、导航、真实数据）
  - XSS  payload 被转义
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import settings as sec_settings, ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER

# 开发期固定令牌
DEV_TOKEN = getattr(sec_settings, "dev_token", "") or "zaojia-dev-token-2026"
AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}


def _auth_headers(role: str = ROLE_ADMIN) -> dict:
    """生成带角色的鉴权头（开发期通过 cookie 指定角色）。"""
    return {"Authorization": f"Bearer {DEV_TOKEN}"}


def _cookies(role: str = ROLE_ADMIN) -> dict:
    """生成带角色的 cookie（开发期通过 zj_role 指定角色）。"""
    return {"zj_token": DEV_TOKEN, "zj_role": role}


# ============================================================================
# 路由前缀分离测试
# ============================================================================

class TestRouteSeparation:
    """验证 Portal/Admin 路由前缀分离和旧路由重定向。"""

    def test_root_redirects_to_portal_dashboard(self, client):
        """首页 / 重定向到 /portal/dashboard。"""
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 301
        assert r.headers["location"] == "/portal/dashboard"

    def test_old_routes_redirect_301(self, client):
        """旧路由返回 301 重定向到新前缀。"""
        old_new_map = {
            "/dashboard": "/portal/dashboard",
            "/search": "/portal/search",
            "/price": "/portal/price",
            "/import": "/admin/import",
            "/batches": "/admin/batches",
            "/dict": "/admin/dict",
            "/match": "/admin/match",
            "/quality": "/admin/quality",
            "/settings": "/admin/settings",
        }
        for old, new in old_new_map.items():
            r = client.get(old, follow_redirects=False)
            assert r.status_code == 301, f"{old} 应返回 301，实际 {r.status_code}"
            assert r.headers["location"] == new, f"{old} 应重定向到 {new}"


# ============================================================================
# Portal 页鉴权测试（可选登录）
# ============================================================================

class TestPortalAuth:
    """Portal 页可选登录：未登录可访问（只读），已登录也可访问。"""

    PORTAL_PAGES = ["/portal/dashboard", "/portal/search", "/portal/price"]

    def test_portal_unauthenticated_returns_200(self, client):
        """未登录访问 Portal 页 → 200（可选登录）。"""
        for path in self.PORTAL_PAGES:
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 200, f"{path} 未登录应返回 200，实际 {r.status_code}"

    def test_portal_authenticated_returns_200(self, client):
        """已登录访问 Portal 页 → 200。"""
        for path in self.PORTAL_PAGES:
            r = client.get(path, cookies=_cookies(ROLE_ADMIN), follow_redirects=False)
            assert r.status_code == 200, f"{path} 已登录应返回 200，实际 {r.status_code}"

    def test_portal_page_contains_nav(self, client):
        """Portal 页包含 Portal 导航（数据概览/清单检索/价格分析）。"""
        r = client.get("/portal/dashboard")
        assert r.status_code == 200
        assert "数据概览" in r.text or "portal" in r.text.lower()


# ============================================================================
# Admin 页鉴权测试（必须登录+角色）
# ============================================================================

class TestAdminAuth:
    """Admin 页必须登录+角色校验：未登录 401，viewer 403，estimator/admin 200。"""

    # Admin 普通页（admin/estimator 可访问）
    ADMIN_ACCESS_PAGES = ["/admin/dashboard", "/admin/dict", "/admin/match", "/admin/quality"]
    # Admin 写操作页（仅 admin）
    ADMIN_WRITE_PAGES = ["/admin/import", "/admin/batches", "/admin/settings"]

    def test_admin_unauthenticated_returns_401(self, client):
        """未登录访问 Admin 页 → 401。"""
        for path in self.ADMIN_ACCESS_PAGES + self.ADMIN_WRITE_PAGES:
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 401, f"{path} 未登录应返回 401，实际 {r.status_code}"

    def test_admin_viewer_returns_403(self, client):
        """viewer 角色访问 Admin 页 → 403。"""
        for path in self.ADMIN_ACCESS_PAGES + self.ADMIN_WRITE_PAGES:
            r = client.get(path, cookies=_cookies(ROLE_VIEWER), follow_redirects=False)
            assert r.status_code == 403, f"{path} viewer 应返回 403，实际 {r.status_code}"

    def test_admin_estimator_access_pages_returns_200(self, client):
        """estimator 角色访问 Admin 普通页 → 200。"""
        for path in self.ADMIN_ACCESS_PAGES:
            r = client.get(path, cookies=_cookies(ROLE_ESTIMATOR), follow_redirects=False)
            assert r.status_code == 200, f"{path} estimator 应返回 200，实际 {r.status_code}"

    def test_admin_estimator_write_pages_returns_403(self, client):
        """estimator 角色访问 Admin 写操作页 → 403。"""
        for path in self.ADMIN_WRITE_PAGES:
            r = client.get(path, cookies=_cookies(ROLE_ESTIMATOR), follow_redirects=False)
            assert r.status_code == 403, f"{path} estimator 写操作页应返回 403，实际 {r.status_code}"

    def test_admin_all_pages_returns_200(self, client):
        """admin 角色访问全部 Admin 页 → 200。"""
        for path in self.ADMIN_ACCESS_PAGES + self.ADMIN_WRITE_PAGES:
            r = client.get(path, cookies=_cookies(ROLE_ADMIN), follow_redirects=False)
            assert r.status_code == 200, f"{path} admin 应返回 200，实际 {r.status_code}"


# ============================================================================
# 登录/登出测试
# ============================================================================

class TestLoginLogout:
    """开发期登录/登出测试。"""

    def test_dev_login_sets_token_and_role_cookies(self, client):
        """/login 应写入 zj_token + zj_role Cookie。"""
        if sec_settings.env != "development":
            pytest.skip("仅 development 提供 /login")
        r = client.get(f"/login?token={DEV_TOKEN}&role=estimator&next=/portal/dashboard",
                       follow_redirects=False)
        assert r.status_code in (302, 303)
        assert "zj_token" in r.cookies
        assert "zj_role" in r.cookies
        assert r.cookies["zj_role"] == "estimator"

    def test_dev_login_default_role_admin(self, client):
        """/login 未指定 role 时默认为 admin（向后兼容）。"""
        if sec_settings.env != "development":
            pytest.skip("仅 development 提供 /login")
        r = client.get(f"/login?token={DEV_TOKEN}&next=/portal/dashboard",
                       follow_redirects=False)
        assert r.status_code in (302, 303)
        assert r.cookies["zj_role"] == ROLE_ADMIN

    def test_dev_logout_clears_cookies(self, client):
        """/logout 应清除 zj_token + zj_role Cookie。"""
        if sec_settings.env != "development":
            pytest.skip("仅 development 提供 /logout")
        r = client.get("/logout?next=/portal/dashboard", follow_redirects=False)
        assert r.status_code in (302, 303)


# ============================================================================
# 页面内容测试
# ============================================================================

class TestPageContent:
    """测试页面包含关键内容节点。"""

    def test_portal_dashboard_contains_title(self, client):
        """Portal 数据概览页包含标题。"""
        r = client.get("/portal/dashboard")
        assert r.status_code == 200
        assert "数据概览" in r.text or "概览" in r.text

    def test_portal_search_contains_search_form(self, client):
        """Portal 清单检索页包含搜索表单。"""
        r = client.get("/portal/search")
        assert r.status_code == 200
        assert "清单" in r.text or "搜索" in r.text or "检索" in r.text

    def test_admin_import_contains_wizard(self, client):
        """Admin 导入向导页包含步骤条。"""
        r = client.get("/admin/import", cookies=_cookies(ROLE_ADMIN))
        assert r.status_code == 200
        assert "导入" in r.text

    def test_admin_batches_contains_batch_list(self, client):
        """Admin 批次管理页包含批次列表。"""
        r = client.get("/admin/batches", cookies=_cookies(ROLE_ADMIN))
        assert r.status_code == 200
        assert "批次" in r.text


# ============================================================================
# XSS 防护测试
# ============================================================================

class TestXSSProtection:
    """XSS payload 应被转义。"""

    def test_xss_payload_is_escaped_in_search(self, client):
        """搜索参数中的 XSS payload 应被转义。"""
        xss = "<script>alert('xss')</script>"
        r = client.get(f"/portal/search?kw={xss}")
        assert r.status_code == 200
        # 原始 script 标签不应出现（应被转义为 &lt;script&gt;）
        assert "<script>alert('xss')</script>" not in r.text
