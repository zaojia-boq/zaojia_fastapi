# -*- coding: utf-8 -*-
"""field_spec —— 字段分层定义（A/B/C 类），数据安全的根基。

从 Odoo 版 zaojia_boq/models/boq_item.py:31 与 services/upsert_service.py:27-46
抽取，作为纯常量层（零框架依赖），供 SQLAlchemy 模型、Upsert 服务、审计服务、
权限校验共同引用。**单一事实源**：任何涉及"B 类禁静默覆盖"的逻辑都必须引用
本文件的常量，不得在代码里重新硬编码字段列表。

设计来源：M1模块设计.md §4.9 数据分层（A/B/C）、架构设计.md §4.5。

分层原则（第一性原理）：
- A 类（可重建）：从原始 Excel 解析出的派生物，重导允许覆盖更新。
- B 类（不可重建）：人工标注资产，禁止删除、禁止静默覆盖（已有值原样保留）。
- C 类（系统元数据）：write_date / active 等，由系统维护。

铁律：B 类字段的任何变更必须带 reason（审计四元组），无 reason 拒绝写入。
"""

# A 类 · 可重建 —— 重导允许覆盖更新
# 来源：upsert_service.py:27-33
A_FIELDS = frozenset([
    'item_code', 'item_code_raw', 'item_name', 'item_feature',
    'unit', 'unit_std', 'ordinal', 'sub_division', 'sequence',
    'quantity', 'quantity_num', 'unit_rate', 'unit_rate_num',
    'total', 'total_num', 'provisional_sum', 'provisional_sum_num',
    'classification', 'extra', 'source_path', 'source_sheet',
])

# B 类 · 不可重建 —— 禁止删除、禁止静默覆盖（已有值原样保留）
# 来源：boq_item.py:31-34 与 upsert_service.py:36-40（两处已核对一致）
B_FIELDS = frozenset([
    'std_name', 'std_spec', 'material_dict_id',
    'anomaly_flag', 'anomaly_reason',
    'data_source_type',
])

# C 类 · 系统元数据 —— 由系统维护，不参与 A/B 分层覆盖逻辑
C_FIELDS = frozenset([
    'id', 'biz_id', 'create_date', 'write_date', 'create_uid', 'write_uid',
    'active', 'match_key', 'match_key_source', 'aggregate_id',
])

# 已完工程批次导入时的 B 类默认值（空则填；已有值不覆盖）
# 来源：upsert_service.py:43-46
B_DEFAULTS = {
    'anomaly_flag': 'normal',
    'data_source_type': 'completed',
}

# 数据性质枚举（data_source_type 字段的合法取值）
# 来源：M1模块设计.md §4.7、产品设计文档.md §7.3
DATA_SOURCE_TYPES = frozenset([
    'completed',        # 已完工程（结算/审计定案的真实单价）—— 算进历史均价
    'control_price',    # 招标控制价 / 预算价 —— 不算（想算要手动勾）
    'bid_price',        # 投标报价 —— 不算
    'pending_review',   # 待审清单 —— 永远不算，只当被比对的一方
    'info_price',       # 信息价 / 市场价 —— 不算
])

# 算进历史均价的数据性质（默认只用已完工程）
# 来源：产品设计文档.md §7.3、架构设计.md §4.8
PRICE_STAT_TYPES = frozenset(['completed'])


def is_b_field(field_name: str) -> bool:
    """判断字段是否为 B 类（不可重建）。

    B 类字段变更必须带 reason，无 reason 拒绝写入。
    """
    return field_name in B_FIELDS


def is_a_field(field_name: str) -> bool:
    """判断字段是否为 A 类（可重建，重导允许覆盖）。"""
    return field_name in A_FIELDS


def is_c_field(field_name: str) -> bool:
    """判断字段是否为 C 类（系统元数据）。"""
    return field_name in C_FIELDS


def classify_field(field_name: str) -> str:
    """返回字段分层标签：'A' / 'B' / 'C' / 'unknown'。

    用于审计日志记录字段变更时的分层标注。
    """
    if field_name in B_FIELDS:
        return 'B'
    if field_name in A_FIELDS:
        return 'A'
    if field_name in C_FIELDS:
        return 'C'
    return 'unknown'


def split_fields_by_layer(field_names) -> dict:
    """将字段列表按 A/B/C/unknown 分层，返回 dict。

    用于 Upsert 服务在写入前分离可覆盖字段与禁覆盖字段。
    """
    result = {'A': [], 'B': [], 'C': [], 'unknown': []}
    for f in field_names:
        result[classify_field(f)].append(f)
    return result


# 完整性自检：A/B/C 三类不应有交集
assert A_FIELDS.isdisjoint(B_FIELDS), "A_FIELDS 与 B_FIELDS 有交集"
assert A_FIELDS.isdisjoint(C_FIELDS), "A_FIELDS 与 C_FIELDS 有交集"
assert B_FIELDS.isdisjoint(C_FIELDS), "B_FIELDS 与 C_FIELDS 有交集"
