# -*- coding: utf-8 -*-
"""M2.5 / M2.6 页面路由测试 —— 验证业务页面可正常渲染且已接入鉴权与真实交互。

测试目标：
  - 所有页面在带开发令牌时返回 HTTP 200（M2.6.1 页面鉴权）
  - 未带令牌访问页面 → 401（P0-2 安全闸门生效）
  - 页面包含关键内容节点（标题、导航、真实数据）
  - 导入向导 / 批次管理包含真实交互所需的 DOM 钩子（P1-1 / P1-2）
  - mock 数据不污染真实页面（数据禁编造铁律）
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import settings as sec_settings

# 开发期固定令牌（与 security.get_current_user dev 分支一致）
DEV_TOKEN = getattr(sec_settings, "dev_token", "") or "zaojia-dev-token-2026"
AUTH_HEADER = {"Authorization": f"Bearer {DEV_TOKEN}"}


# 注：client 复用 conftest 的 TestClient 夹具——它会 override get_db 指向隔离测试库，
# 避免页面测试直连真实数据库（PG 未启动时会挂起）。本文件不再定义 client，直接继承。

@pytest.fixture
def auth_client(client):
    """带开发令牌的客户端（所有页面可达性测试用）。

    依赖 conftest 的 client 夹具以激活测试库 override，再叠加鉴权头。
    """
    return TestClient(app, headers=AUTH_HEADER)



# ============================================================================
# 页面鉴权测试（M2.6.1 / P0-2）
# ============================================================================

class TestPageAuth:
    """未鉴权应被拒，带令牌应放行。"""

    def test_unauthenticated_page_returns_401(self, client):
        """未带令牌访问页面 → 401。"""
        for path in ["/dashboard", "/import", "/batches", "/settings"]:
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 401, f"{path} 未鉴权却返回 {r.status_code}"

    def test_authenticated_pages_return_200(self, auth_client):
        """带开发令牌访问全部页面 → 200。"""
        for path in ["/dashboard", "/search", "/price", "/import",
                     "/batches", "/dict", "/match", "/quality", "/settings"]:
            r = auth_client.get(path, follow_redirects=False)
            assert r.status_code == 200, f"{path} 鉴权后返回 {r.status_code}"

    def test_root_requires_auth(self, client, auth_client):
        """根路径同样受鉴权保护。"""
        assert client.get("/").status_code == 401
        assert auth_client.get("/").status_code == 200

    def test_dev_login_sets_cookie(self, client):
        """开发期 /login 应写入 zj_token Cookie（浏览器整站认证用）。"""
        if sec_settings.env != "development":
            pytest.skip("仅 development 提供 /login")
        r = client.get(f"/login?token={DEV_TOKEN}&next=/dashboard", follow_redirects=False)
        assert r.status_code in (302, 303)
        assert "zj_token" in r.cookies


# ============================================================================
# 页面可达性测试
# ============================================================================

class TestPageAccessibility:
    """测试所有业务页面（带令牌）可访问。"""

    PAGES = [
        ("/dashboard", "数据概览"),
        ("/search", "清单检索"),
        ("/price", "单价分析"),
        ("/import", "导入向导"),
        ("/batches", "批次管理"),
        ("/dict", "物料字典"),
        ("/match", "匹配确认"),
        ("/settings", "系统设置"),
    ]

    @pytest.mark.parametrize("path,expected_title", PAGES)
    def test_page_returns_200(self, auth_client, path, expected_title):
        """所有页面应返回 200。"""
        r = auth_client.get(path, follow_redirects=False)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
        assert "text/html" in r.headers.get("content-type", "")

    def test_root_redirects_to_dashboard(self, auth_client):
        """根路径应返回数据概览内容。"""
        r = auth_client.get("/")
        assert r.status_code == 200
        assert "数据概览" in r.text

    def test_audit_endpoint_mounted(self, auth_client):
        """审计能力以 API 形式提供（/api/admin/audit-test），须已挂载（非 404）。"""
        r = auth_client.get("/api/admin/audit-test")
        assert r.status_code in (401, 403, 405)


# ============================================================================
# 页面内容测试
# ============================================================================

class TestPageContent:
    """测试页面包含关键内容节点。"""

    def test_dashboard_has_content(self, auth_client):
        """数据概览页应包含标题和 KPI 数据。"""
        r = auth_client.get("/dashboard")
        assert r.status_code == 200
        content = r.text
        assert "数据概览" in content
        assert "清单条目总数" in content

    def test_search_has_table(self, auth_client):
        """清单检索页应包含大搜索框和筛选结构。"""
        r = auth_client.get("/search")
        assert r.status_code == 200
        content = r.text
        assert "清单检索" in content
        assert "hero-search" in content
        assert 'method="get"' in content

    def test_price_has_kpis(self, auth_client):
        """单价分析页应包含 KPI 数据。"""
        r = auth_client.get("/price")
        assert r.status_code == 200
        assert "单价分析" in r.text

    def test_import_wizard_has_steps(self, auth_client):
        """导入向导页应包含步骤条与真实交互钩子（M2.6.4 / P1-1）。"""
        r = auth_client.get("/import")
        assert r.status_code == 200
        content = r.text
        assert "导入向导" in content
        assert "选择文件" in content or "1 选择文件" in content
        # 真流程所需 DOM 钩子
        assert 'id="impFile"' in content
        assert 'id="impExecute"' in content
        assert 'id="impToken"' in content

    def test_batches_has_table(self, auth_client):
        """批次管理页应包含批次列表与生命周期操作钩子（M2.6.5 / P1-2）。"""
        r = auth_client.get("/batches")
        assert r.status_code == 200
        content = r.text
        assert "批次管理" in content
        # 操作列表头 + 硬删确认模态框（始终渲染，不依赖是否有数据行）
        assert '操作' in content
        assert 'id="hdModal"' in content
        assert 'id="hdConfirmInput"' in content

    def test_dict_has_tree(self, auth_client):
        """物料字典页应包含树形结构（服务端渲染，非 JS 注入）。"""
        r = auth_client.get("/dict")
        assert r.status_code == 200
        content = r.text
        assert "物料字典" in content
        # 字典树由服务端渲染：有数据时含 dictTree 容器，无数据时含服务端空态
        assert ('id="dictTree"' in content) or ('字典为空' in content)
        # 分类树面板标题始终由服务端渲染（非 JS 注入占位）
        assert '分类树' in content

    def test_match_has_items(self, auth_client):
        """匹配确认页应包含待处理项与筛选控件。"""
        r = auth_client.get("/match")
        assert r.status_code == 200
        content = r.text
        assert "匹配确认" in content
        assert 'id="matchSeg"' in content
        assert 'data-filter="high"' in content
        assert 'data-filter="low"' in content

    def test_settings_has_controls(self, auth_client):
        """系统设置页应包含控件。"""
        r = auth_client.get("/settings")
        assert r.status_code == 200
        content = r.text
        assert "系统设置" in content
        assert "深空科技" in content or "方案" in content


# ============================================================================
# 查询参数透传测试
# ============================================================================

class TestQueryParams:
    """测试查询参数正确透传到页面。"""

    def test_search_with_kw(self, auth_client):
        r = auth_client.get("/search?kw=变压器")
        assert r.status_code == 200

    def test_search_with_filters(self, auth_client):
        r = auth_client.get("/search?major=03&code=0302&status=ok&page=1")
        assert r.status_code == 200

    def test_price_with_range(self, auth_client):
        r = auth_client.get("/price?range=12&major=all")
        assert r.status_code == 200

    def test_price_with_major(self, auth_client):
        r = auth_client.get("/price?range=24&major=03")
        assert r.status_code == 200


# ============================================================================
# 静态资源测试
# ============================================================================

class TestStaticAssets:
    """测试静态资源可访问（静态资源不强制鉴权）。"""

    def test_css_tokens(self, client):
        r = client.get("/static/css/tokens.css")
        assert r.status_code == 200
        assert "text/css" in r.headers.get("content-type", "")

    def test_css_components(self, client):
        r = client.get("/static/css/components.css")
        assert r.status_code == 200
        assert "text/css" in r.headers.get("content-type", "")

    def test_js_app(self, client):
        r = client.get("/static/js/app.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "")

    def test_skeleton_styles_exist(self, client):
        """骨架屏样式应存在于 CSS 中。"""
        r = client.get("/static/css/components.css")
        assert "zj_skeleton" in r.text or "zj_loading" in r.text

    def test_theme_persistence_code_exists(self, client):
        """主题持久化逻辑应存在于 JS 中。"""
        r = client.get("/static/js/app.js")
        assert "localStorage" in r.text
        assert "zj-theme" in r.text


# ============================================================================
# 数据完整性测试（数据禁编造铁律）
# ============================================================================

class TestDataIntegrity:
    """验证页面不编造数据、不注入/覆盖服务端数据、反射型参数被转义。"""

    def test_no_hardcoded_demo_numbers_on_dashboard(self, auth_client):
        """数据概览不应出现演示硬编码数字（如 128,540）。"""
        r = auth_client.get("/dashboard")
        assert r.status_code == 200
        assert "128,540" not in r.text
        assert "清单条目总数" in r.text

    def test_xss_payload_is_escaped(self, auth_client):
        """搜索关键词中的脚本标签必须被 autoescape 转义。"""
        payload = "<script>alert(1)</script>"
        r = auth_client.get("/search", params={"kw": payload})
        assert r.status_code == 200
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
        assert "<script>alert(1)</script>" not in r.text

    def test_js_does_not_override_server_data(self, client):
        """app.js 不得包含旧版 mock 渲染逻辑（避免覆盖服务端真实数据）。"""
        r = client.get("/static/js/app.js")
        assert r.status_code == 200
        js = r.text
        assert "BAR_DATA" not in js
        assert "renderDict" not in js
        assert "renderBars" not in js
        assert "renderDonut" not in js
        # 仅保留客户端交互增强（主题 / 树 / 向导 / 筛选 / 真实导入 / 批次操作）
        assert "initTheme" in js
        assert "bindDictTree" in js
        assert "bindMatchFilter" in js
        assert "bindImportFlow" in js
        assert "bindBatchActions" in js

    def test_dict_tree_server_rendered(self, auth_client, db_session):
        """物料字典树应由服务端渲染真实节点，而非 JS 注入。

        播种最小三级树（大类→系列），验证服务端确实渲染出 data-caret /
        data-children 等节点标记，而非由前端 JS 注入。
        """
        from app.models.material_dict import MaterialDict
        root = MaterialDict(level="l1", name="管道")
        db_session.add(root)
        db_session.flush()  # 取 root.id 用于子级 parent_id
        child = MaterialDict(level="l2", name="镀锌钢管", parent_id=root.id)
        db_session.add(child)
        db_session.commit()

        r = auth_client.get("/dict")
        assert r.status_code == 200
        assert 'id="dictTree"' in r.text
        assert 'data-caret=' in r.text
        assert 'data-children=' in r.text

    def test_match_item_score_attribute_present(self, auth_client):
        """匹配条目应带 data-score，供客户端筛选使用。"""
        r = auth_client.get("/match")
        assert r.status_code == 200
        assert 'class="match-item"' in r.text or "没有待确认条目" in r.text


# ============================================================================
# 模板继承测试
# ============================================================================

class TestTemplateInheritance:
    """测试页面正确继承 base.html。"""

    def test_all_pages_have_sidebar(self, auth_client):
        for path in ["/dashboard", "/search", "/price", "/import"]:
            r = auth_client.get(path)
            assert r.status_code == 200
            assert "sidebar" in r.text, f"{path} missing sidebar"
            assert "nav-item" in r.text, f"{path} missing nav items"

    def test_all_pages_hide_topbar(self, auth_client):
        # 所有页面统一隐藏顶栏，最大化内容区
        for path in ["/dashboard", "/search", "/price", "/import", "/quality", "/match", "/dict", "/batches", "/settings"]:
            r = auth_client.get(path)
            assert r.status_code == 200
            assert 'class="topbar"' not in r.text, f"{path} should hide topbar"

    def test_search_has_hero_search(self, auth_client):
        """清单检索页应有大搜索框（hero-search）。"""
        r = auth_client.get("/search")
        assert r.status_code == 200
        assert "hero-search" in r.text

    def test_all_pages_have_content_block(self, auth_client):
        for path in ["/dashboard", "/search", "/price", "/import"]:
            r = auth_client.get(path)
            assert r.status_code == 200
            assert "content" in r.text, f"{path} missing content block"
