# -*- coding: utf-8 -*-
"""权限体系（M1.5）。

三角色权限矩阵（与 Odoo 版对齐）：
| 能力 | admin | estimator | viewer |
|---|---|---|---|
| 查询/浏览 | ✅ | ✅ | ✅ |
| 导出 | ✅ | ✅ | ❌ |
| 导入 | ✅ | ❌ | ❌ |
| 修改 A 类字段 | ✅ | ✅ | ❌ |
| 修改 B 类字段（标注） | ✅ | ❌ | ❌ |
| 软删除/还原 | ✅ | ❌ | ❌ |
| 硬删除 | ✅（需闸门） | ❌ | ❌ |
| 用户管理 | ✅ | ❌ | ❌ |

B 类字段保护铁律（M1 §4.9）：
- B 类字段（std_name/std_spec/material_dict_id/anomaly_flag/anomaly_reason/data_source_type）
  不可重建、不可静默丢失；
- 修改 B 类字段必须有 reason（人工填写变更原因），无 reason 拒绝；
- B 类字段常量单一事实源：data/field_spec.py B_FIELDS。

模块定位（2026-09-06 审查澄清）：
- **路由级权限**：当前业务统一使用 `security.py` 的 `require_role(*roles)`（基于角色的粗粒度控制），
  所有 API 路由和页面路由均已接入。
- **本文件 `require_permission(permission)`**：基于权限矩阵的细粒度控制，是 `require_role` 的
  替代/补充方案。bug 已于 2026-09-06 修复（直接 `Depends(get_current_user)`，不再用工厂嵌套），
  待 OA SSO 对接后角色细化、需要按能力（而非按角色）授权时启用。
- **`validate_b_field_change` / `filter_b_fields_for_role`**：Service 层 B 类字段保护工具，
  当前各 Service 内联实现了等价逻辑（`if not existing.<field>` 仅填空不覆盖 + reason 强制），
  待 M3+ 批量标注功能重构时统一收敛到本文件，消除重复实现。
- **`has_permission` / `_ROLE_PERMISSIONS`**：权限矩阵单一事实源，测试和文档引用。
"""
from typing import Optional, Set

from fastapi import HTTPException, status

from app.core.security import ROLE_ADMIN, ROLE_ESTIMATOR, ROLE_VIEWER, get_current_user
from data.field_spec import B_FIELDS


# ------------------------------------------------------------------
# 角色权限矩阵
# ------------------------------------------------------------------
# 各角色允许的操作集合
_ROLE_PERMISSIONS = {
    ROLE_ADMIN: {
        "query", "export", "import", "edit_a", "edit_b",
        "soft_delete", "restore", "hard_delete", "user_manage",
    },
    ROLE_ESTIMATOR: {
        "query", "export", "edit_a",
    },
    ROLE_VIEWER: {
        "query",
    },
}


def has_permission(role: str, permission: str) -> bool:
    """检查角色是否拥有指定权限。"""
    return permission in _ROLE_PERMISSIONS.get(role, set())


def require_permission(permission: str):
    """权限检查依赖工厂。

    用法：
        @app.post("/import")
        async def import_data(user=Depends(require_permission("import"))):
            ...

    注意（2026-09-06 审查修复）：必须写成「直接依赖 get_current_user」，
    不能写成 ``Depends(_get_user)`` 这类「返回函数的函数」——FastAPI 会把
    返回值（函数对象本身）注入为 user，不再解析其内部 Depends，导致鉴权
    被完全绕过（与 pages.py require_page_admin 曾出现的 P0 同型）。
    """
    async def checker(user=Depends(get_current_user)):
        if not has_permission(user["role"], permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"角色 {user['role']} 无权限执行: {permission}",
            )
        return user
    return checker


# ------------------------------------------------------------------
# B 类字段保护
# ------------------------------------------------------------------
def get_b_fields() -> Set[str]:
    """获取 B 类字段集合（单一事实源：data/field_spec.py）。"""
    return set(B_FIELDS)


def is_b_field(field_name: str) -> bool:
    """判断字段是否为 B 类字段。"""
    return field_name in B_FIELDS


def validate_b_field_change(
    field_name: str,
    old_value,
    new_value,
    reason: Optional[str] = None,
    operator_role: str = ROLE_ESTIMATOR,
) -> None:
    """验证 B 类字段变更（M1 §4.9 铁律）。

    规则：
    1. 非 B 类字段 → 直接放行；
    2. B 类字段无实际变化（old == new）→ 放行（不写审计）；
    3. B 类字段有变化 → 必须满足：
       a. operator_role == admin（estimator/viewer 不可改 B 类）；
       b. reason 非空（人工填写变更原因）。
    任一不满足 → 抛 HTTPException 403 拒绝。

    参数
    ----
    field_name : str —— 字段名
    old_value : any —— 变更前值
    new_value : any —— 变更后值
    reason : str, optional —— 变更原因（B 类字段必填）
    operator_role : str —— 操作人角色（admin/estimator/viewer）

    异常
    ----
    HTTPException 403 —— 无权限或缺少 reason
    """
    # 非 B 类字段 → 放行
    if not is_b_field(field_name):
        return

    # B 类字段无实际变化 → 放行
    if old_value == new_value:
        return

    # B 类字段有变化 → 检查角色
    if operator_role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"B 类字段「{field_name}」仅 admin 可修改，"
                   f"当前角色 {operator_role} 无权限。请通过「修改标注」向导由管理员操作。",
        )

    # B 类字段有变化 → 检查 reason
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"修改 B 类字段「{field_name}」必须填写变更原因（reason）。"
                   f"禁止直接编辑 B 类字段，请通过「修改标注」向导填写原因。",
        )


def filter_b_fields_for_role(
    data: dict,
    role: str,
    reason: Optional[str] = None,
) -> dict:
    """按角色过滤可写入字段（Service 层调用）。

    - admin + reason → 全部字段可写；
    - admin 无 reason → B 类字段被剥离（只写 A/C 类）；
    - estimator/viewer → B 类字段被剥离（只写 A/C 类）。

    返回可安全写入的字段字典。被剥离的 B 类字段记录在返回值的 _stripped_b_fields 中。
    """
    result = {}
    stripped = []
    for key, value in data.items():
        if is_b_field(key):
            if role == ROLE_ADMIN and reason and reason.strip():
                result[key] = value
            else:
                stripped.append(key)
        else:
            result[key] = value
    if stripped:
        result["_stripped_b_fields"] = stripped
    return result
