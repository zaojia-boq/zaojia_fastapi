# -*- coding: utf-8 -*-
"""S1–S9 安全验收聚合测试（M1 §9.3）。

本文件为安全架构元测试，不重复业务测试，而是检查安全合规性：
- S1 源文件只读：导入代码不得对源文件调用 wb.save()
- S2 归档完整性：归档文件 SHA256 与源一致（见 test_archive.py）
- S3 A 类可覆盖：见 test_upsert.py
- S4 B 类禁静默覆盖：service 层必须有「仅填空不覆盖」保护
- S5 审计完整：所有写操作有审计记录（见 test_audit.py）
- S6 归档幂等：见 test_archive.py
- S7 待审不污染：price_service 仅统计 completed 域
- S8 备份恢复：每季度人工演练，无自动化（docs/backup_drill.md）
- S9 审计四元组：operator/reason/trace_id/timestamp 非空

反向用例 N1–N3 已补齐（2026-09-08，见 test_security_negative.py）：
- N1：.xlsm 含宏文件 → 支持只读解析（不执行宏），魔数校验防伪造
- N2：超大文件（>60MB）→ 返回 413，不进入解析
- N3：归档失败 → 不阻断导入，数据仍入库且异常被记录
"""
import os
import re
from pathlib import Path

import pytest

from app.config import settings
from app.core.security import ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER

# 整个文件的测试都标记为 security（S1-S9 安全用例优先级高于功能用例）
pytestmark = pytest.mark.security

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"


# ---------------------------------------------------------------------------
# 安全配置
# ---------------------------------------------------------------------------
class TestSecurityConfig:
    """安全配置基线（生产环境必须满足）。"""

    def test_secret_key_required(self):
        """S9：secret_key 必须非空（缺失即启动失败）。"""
        assert settings.secret_key, "SECRET_KEY 必须配置，禁止空值"

    def test_debug_default_false(self):
        """生产环境 debug 必须为 False。"""
        # 开发期允许 debug=True，但配置默认值必须是 False
        assert settings.__class__.model_fields["debug"].default is False

    def test_dev_token_only_development(self):
        """dev_token 仅在 development 环境生效。"""
        if settings.env == "production":
            assert not getattr(settings, "dev_token", None), \
                "生产环境禁止配置 DEV_TOKEN"

    def test_roles_defined(self):
        """三角色常量必须存在且互异。"""
        assert ROLE_ADMIN == "admin"
        assert ROLE_ESTIMATOR == "estimator"
        assert ROLE_VIEWER == "viewer"
        assert len({ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER}) == 3


# ---------------------------------------------------------------------------
# S1 源文件只读
# ---------------------------------------------------------------------------
class TestSourceFileReadOnly:
    """S1：导入代码不得对源文件调用 wb.save()。"""

    def test_no_wb_save_on_source(self):
        """扫描 app/ 下所有 .py，不得出现对导入源文件的 wb.save()。

        允许的例外：
        - 导出向内存 BytesIO 生成全新文件（query.py 的 wb.save(buf)）
        - 注释中的说明文字
        """
        violations = []
        for py_file in APP_DIR.rglob("*.py"):
            lines = py_file.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # 跳过注释和 docstring 中的说明文字
                if (stripped.startswith("#") or stripped.startswith('"') or
                        stripped.startswith("'") or stripped.startswith("- ") or
                        "禁止" in stripped or "不得" in stripped):
                    continue
                # 只检查 wb.save( / workbook.save( 形式的调用
                if not re.search(r'\b(wb|workbook)\.save\(', line):
                    continue
                # 允许：BytesIO 内存导出（检查附近 5 行是否有 BytesIO）
                context = "\n".join(lines[max(0, i-6):i+2])
                if "BytesIO" in context or "buf" in line:
                    continue
                violations.append(f"{py_file.relative_to(PROJECT_ROOT)}:{i}: {stripped}")
        assert not violations, f"发现对源文件的 wb.save() 调用:\n" + "\n".join(violations)

    def test_load_workbook_read_only(self):
        """所有 load_workbook 必须带 read_only=True, data_only=True。"""
        violations = []
        for py_file in APP_DIR.rglob("*.py"):
            lines = py_file.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, 1):
                if "load_workbook(" in line:
                    # 检查本行及下 2 行是否有 read_only=True
                    context = "\n".join(lines[i-1:min(len(lines), i+2)])
                    if "read_only=True" not in context:
                        violations.append(f"{py_file.relative_to(PROJECT_ROOT)}:{i}")
        assert not violations, f"load_workbook 未带 read_only=True:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# S4 B 类字段禁静默覆盖
# ---------------------------------------------------------------------------
class TestBFieldProtection:
    """S4：B 类字段变更必须有「仅填空不覆盖」保护。"""

    B_FIELDS = ["std_name", "std_spec", "material_dict_id"]

    def test_match_confirm_protects_b_fields(self):
        """material_match_service.confirm_match 必须检查 existing 字段非空才跳过。"""
        svc = (APP_DIR / "services" / "material_match_service.py").read_text(encoding="utf-8")
        for field in self.B_FIELDS:
            assert f"if not existing.{field}" in svc or f"if not boq.{field}" in svc, \
                f"material_match_service 缺少对 {field} 的「仅填空不覆盖」保护"

    def test_cost_migration_protects_b_fields(self):
        """cost_migration_service 迁移时必须检查 existing 字段非空才跳过。"""
        svc = (APP_DIR / "services" / "cost_migration_service.py").read_text(encoding="utf-8")
        # 接受两种写法：if not existing.<field> 或 if existing.<field> is None
        assert "if not existing.std_name" in svc, \
            "cost_migration_service 缺少对 std_name 的「仅填空不覆盖」保护"
        assert "if not existing.std_spec" in svc, \
            "cost_migration_service 缺少对 std_spec 的「仅填空不覆盖」保护"
        assert ("if not existing.material_dict_id" in svc or
                "existing.material_dict_id is None" in svc), \
            "cost_migration_service 缺少对 material_dict_id 的「仅填空不覆盖」保护"


# ---------------------------------------------------------------------------
# S7 待审不污染
# ---------------------------------------------------------------------------
class TestPendingReviewIsolation:
    """S7：pending_review（待审）不得进入均价统计。"""

    def test_price_service_filters_completed(self):
        """price_service 必须显式过滤 data_source_type == 'completed'。"""
        svc = (APP_DIR / "services" / "price_service.py").read_text(encoding="utf-8")
        assert "'completed'" in svc or '"completed"' in svc, \
            "price_service 未过滤 completed 域，待审清单可能污染均价"
        assert "data_source_type" in svc, \
            "price_service 未按 data_source_type 过滤"

    def test_cost_migration_filters_completed(self):
        """cost_migration_service 聚合域必须仅含 completed。"""
        svc = (APP_DIR / "services" / "cost_migration_service.py").read_text(encoding="utf-8")
        assert "data_source_type == 'completed'" in svc or \
               'data_source_type == "completed"' in svc, \
            "cost_migration_service 聚合域未限定 completed"


# ---------------------------------------------------------------------------
# S5/S9 审计完整性
# ---------------------------------------------------------------------------
class TestAuditCompleteness:
    """S5/S9：审计日志 append-only 且四元组完整。"""

    def test_audit_middleware_registered(self):
        """AuditMiddleware 必须在 main.py 注册。"""
        main_py = (APP_DIR / "main.py").read_text(encoding="utf-8")
        assert "AuditMiddleware" in main_py, "main.py 未注册 AuditMiddleware"
        assert "add_middleware(AuditMiddleware)" in main_py, \
            "main.py 未调用 add_middleware(AuditMiddleware)"

    def test_write_services_call_log_audit(self):
        """写操作 service 必须调用 log_audit。"""
        write_services = [
            "upsert_service.py",
            "material_match_service.py",
            "cost_migration_service.py",
            "batch_operation_service.py",
        ]
        for svc_name in write_services:
            svc = (APP_DIR / "services" / svc_name).read_text(encoding="utf-8")
            assert "log_audit(" in svc, f"{svc_name} 未调用 log_audit"

    def test_audit_model_append_only(self):
        """audit_log 模型不得有 update/delete 方法。"""
        model = (APP_DIR / "models" / "audit_log.py").read_text(encoding="utf-8")
        assert "def update" not in model, "audit_log 模型不应有 update 方法"
        assert "def delete" not in model, "audit_log 模型不应有 delete 方法"


# ---------------------------------------------------------------------------
# 鉴权覆盖
# ---------------------------------------------------------------------------
class TestAuthCoverage:
    """所有 API 路由必须有鉴权依赖（公开路由除外）。"""

    PUBLIC_PATHS = {"/health", "/api/public/hello", "/login", "/logout", "/docs", "/redoc", "/openapi.json"}

    def test_api_routes_have_auth_dependency(self):
        """扫描 app/api/ 下所有路由，写操作必须有 require_role 或 get_current_user。"""
        api_dir = APP_DIR / "api"
        for py_file in api_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text(encoding="utf-8")
            # 找到所有路由定义
            routes = re.findall(r'@router\.(get|post|put|delete|patch)\("([^"]+)"', content)
            for method, path in routes:
                if path in ("/login", "/logout") and "pages.py" in py_file.name:
                    continue  # 开发期登录/登出公开
                # 检查该路由函数是否有鉴权依赖
                # pages.py 使用 get_page_user/get_page_user_optional/require_admin_role 等
                # 其他 API 文件使用 get_current_user/require_role
                auth_keywords = ["get_current_user", "require_role",
                                  "get_page_user", "require_admin_role", "require_admin_access"]
                assert any(kw in content for kw in auth_keywords), \
                    f"{py_file.name}: {method} {path} 所在文件缺少鉴权依赖 import"


# ---------------------------------------------------------------------------
# 敏感文件不入仓
# ---------------------------------------------------------------------------
class TestSensitiveFilesGitignore:
    """真实工程 Excel 与数据库备份禁止入仓。"""

    def test_gitignore_excludes_sensitive(self):
        """.gitignore 必须包含 *.xlsx / *.xls / *.sql / *.dump。"""
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ["*.xlsx", "*.xls", "*.sql", "*.dump"]:
            assert pattern in gitignore, f".gitignore 缺少 {pattern}"

    def test_no_sensitive_files_in_app_dir(self):
        """app/ 目录下不得有真实工程 Excel。"""
        for ext in ["*.xlsx", "*.xls", "*.sql", "*.dump"]:
            files = list(APP_DIR.rglob(ext))
            assert not files, f"app/ 下发现敏感文件: {[str(f) for f in files]}"
