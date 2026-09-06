# -*- coding: utf-8 -*-
"""M1.5 权限体系测试。

覆盖：
- 三角色权限矩阵（admin/estimator/viewer）
- B 类字段保护（无 reason 拒绝、非 admin 拒绝）
- filter_b_fields_for_role 字段过滤

运行：
    python.exe -m pytest tests/test_permissions.py -v
"""
import pytest
from fastapi import HTTPException

from app.core.permissions import (
    has_permission, require_permission, get_b_fields, is_b_field,
    validate_b_field_change, filter_b_fields_for_role,
)
from app.core.security import ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER


class TestRolePermissionMatrix:
    """三角色权限矩阵测试。"""

    def test_admin_has_all_permissions(self):
        """admin 拥有所有权限。"""
        for perm in ["query", "export", "import", "edit_a", "edit_b",
                      "soft_delete", "restore", "hard_delete", "user_manage"]:
            assert has_permission(ROLE_ADMIN, perm), f"admin 应有权限: {perm}"

    def test_estimator_permissions(self):
        """estimator：可查询/导出/改 A 类，不可导入/改 B 类/删除。"""
        assert has_permission(ROLE_ESTIMATOR, "query")
        assert has_permission(ROLE_ESTIMATOR, "export")
        assert has_permission(ROLE_ESTIMATOR, "edit_a")
        assert not has_permission(ROLE_ESTIMATOR, "import")
        assert not has_permission(ROLE_ESTIMATOR, "edit_b")
        assert not has_permission(ROLE_ESTIMATOR, "soft_delete")
        assert not has_permission(ROLE_ESTIMATOR, "hard_delete")
        assert not has_permission(ROLE_ESTIMATOR, "user_manage")

    def test_viewer_only_query(self):
        """viewer：仅可查询，不可导出/修改/删除。"""
        assert has_permission(ROLE_VIEWER, "query")
        assert not has_permission(ROLE_VIEWER, "export")
        assert not has_permission(ROLE_VIEWER, "edit_a")
        assert not has_permission(ROLE_VIEWER, "edit_b")
        assert not has_permission(ROLE_VIEWER, "import")
        assert not has_permission(ROLE_VIEWER, "soft_delete")

    def test_unknown_role_has_no_permissions(self):
        """未知角色无任何权限。"""
        assert not has_permission("unknown_role", "query")
        assert not has_permission("unknown_role", "export")


class TestBFieldProtection:
    """B 类字段保护测试（M1 §4.9 铁律）。"""

    def test_b_fields_contains_expected_fields(self):
        """B 类字段集合包含预期的 6 个字段。"""
        b = get_b_fields()
        assert "std_name" in b
        assert "std_spec" in b
        assert "material_dict_id" in b
        assert "anomaly_flag" in b
        assert "anomaly_reason" in b
        assert "data_source_type" in b

    def test_is_b_field(self):
        """is_b_field 判断正确。"""
        assert is_b_field("std_name")
        assert is_b_field("data_source_type")
        assert not is_b_field("item_name")
        assert not is_b_field("quantity")
        assert not is_b_field("unit_rate")

    def test_non_b_field_always_allowed(self):
        """非 B 类字段变更 → 直接放行（任何角色、无 reason 也可以）。"""
        # 不抛异常即通过
        validate_b_field_change("item_name", "旧名", "新名", reason=None, operator_role=ROLE_VIEWER)
        validate_b_field_change("quantity", "100", "200", reason=None, operator_role=ROLE_ESTIMATOR)

    def test_b_field_no_change_allowed(self):
        """B 类字段无实际变化 → 放行（不写审计）。"""
        validate_b_field_change("std_name", "电缆", "电缆", reason=None, operator_role=ROLE_ESTIMATOR)
        validate_b_field_change("anomaly_flag", "normal", "normal", reason=None, operator_role=ROLE_VIEWER)

    def test_b_field_change_estimator_rejected(self):
        """B 类字段有变化 + estimator 角色 → 拒绝（403）。"""
        with pytest.raises(HTTPException) as exc_info:
            validate_b_field_change(
                "std_name", "电缆", "电力电缆",
                reason="标准化标注", operator_role=ROLE_ESTIMATOR,
            )
        assert exc_info.value.status_code == 403
        assert "仅 admin 可修改" in str(exc_info.value.detail)

    def test_b_field_change_viewer_rejected(self):
        """B 类字段有变化 + viewer 角色 → 拒绝（403）。"""
        with pytest.raises(HTTPException) as exc_info:
            validate_b_field_change(
                "anomaly_flag", "normal", "warning",
                reason="发现异常", operator_role=ROLE_VIEWER,
            )
        assert exc_info.value.status_code == 403

    def test_b_field_change_admin_no_reason_rejected(self):
        """B 类字段有变化 + admin + 无 reason → 拒绝（403）。"""
        with pytest.raises(HTTPException) as exc_info:
            validate_b_field_change(
                "std_spec", "YJV", "YJV-3x120",
                reason=None, operator_role=ROLE_ADMIN,
            )
        assert exc_info.value.status_code == 403
        assert "必须填写变更原因" in str(exc_info.value.detail)

    def test_b_field_change_admin_empty_reason_rejected(self):
        """B 类字段有变化 + admin + 空白 reason → 拒绝（403）。"""
        with pytest.raises(HTTPException):
            validate_b_field_change(
                "material_dict_id", None, 42,
                reason="   ", operator_role=ROLE_ADMIN,
            )

    def test_b_field_change_admin_with_reason_allowed(self):
        """B 类字段有变化 + admin + 有 reason → 放行。"""
        # 不抛异常即通过
        validate_b_field_change(
            "std_name", "电缆", "电力电缆",
            reason="人工标准化标注", operator_role=ROLE_ADMIN,
        )
        validate_b_field_change(
            "anomaly_flag", "normal", "error",
            reason="审计发现数据异常", operator_role=ROLE_ADMIN,
        )

    def test_data_source_type_is_b_field(self):
        """data_source_type 是 B 类字段（防绕过向导把待审混入历史均价）。"""
        assert is_b_field("data_source_type")
        with pytest.raises(HTTPException):
            validate_b_field_change(
                "data_source_type", "completed", "pending_review",
                reason=None, operator_role=ROLE_ESTIMATOR,
            )


class TestFilterBFieldsForRole:
    """filter_b_fields_for_role 字段过滤测试。"""

    def test_admin_with_reason_keeps_all_fields(self):
        """admin + reason → 全部字段保留。"""
        data = {"item_name": "电缆", "std_name": "电力电缆", "quantity": "100"}
        result = filter_b_fields_for_role(data, ROLE_ADMIN, reason="标注")
        assert "std_name" in result
        assert result["std_name"] == "电力电缆"
        assert "_stripped_b_fields" not in result

    def test_admin_without_reason_strips_b_fields(self):
        """admin 无 reason → B 类字段被剥离。"""
        data = {"item_name": "电缆", "std_name": "电力电缆", "anomaly_flag": "warning"}
        result = filter_b_fields_for_role(data, ROLE_ADMIN, reason=None)
        assert "std_name" not in result
        assert "anomaly_flag" not in result
        assert "item_name" in result
        assert set(result["_stripped_b_fields"]) == {"std_name", "anomaly_flag"}

    def test_estimator_strips_b_fields(self):
        """estimator → B 类字段被剥离（即使有 reason）。"""
        data = {"item_name": "电缆", "std_name": "电力电缆", "quantity": "100"}
        result = filter_b_fields_for_role(data, ROLE_ESTIMATOR, reason="我想标注")
        assert "std_name" not in result
        assert "item_name" in result
        assert "quantity" in result
        assert result["_stripped_b_fields"] == ["std_name"]

    def test_viewer_strips_b_fields(self):
        """viewer → B 类字段被剥离。"""
        data = {"std_spec": "YJV", "unit": "m"}
        result = filter_b_fields_for_role(data, ROLE_VIEWER)
        assert "std_spec" not in result
        assert "unit" in result

    def test_no_b_fields_returns_unchanged(self):
        """无 B 类字段 → 返回原数据（无 _stripped 键）。"""
        data = {"item_name": "电缆", "quantity": "100", "unit": "m"}
        result = filter_b_fields_for_role(data, ROLE_ESTIMATOR)
        assert result == data
        assert "_stripped_b_fields" not in result
