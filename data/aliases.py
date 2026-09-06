# -*- coding: utf-8 -*-
"""Excel 表头别名映射（M1 §7 落地）。

纯函数模块，**不依赖 odoo**，可被纯函数 pytest 直接 import。

职责边界（硬）：本文件**只解决「表头叫什么」**（列名 → 规范字段）。
物料「同一东西的不同写法」（电缆/电力电缆/YJV）由 material.dict.synonyms
在标准化阶段处理，绝不写进这里（见 §7）。

匹配前先归一化：去所有空白、全角→半角、统一中文标点、英文转小写（见 normalize_header）。
"""
import re

# 规范字段 → 别名表（M1 §7 完整列出）。匹配前所有别名先经 normalize_header 归一化。
ALIASES = {
    'item_code': ['项目编码', '编码', '清单编码', '清单编号', '项目编号', 'item_code', 'code'],
    'item_name': ['项目名称', '名称', '清单名称', '分项名称', '项目', 'item_name', 'name', 'description'],
    'item_feature': ['项目特征', '特征', '特征描述', '项目特征描述', '规格及特征',
                      '规格型号', '规格型号/项目特征', 'feature'],
    'unit': ['计量单位', '单位', '工程量单位', 'unit', 'uom'],
    'quantity': ['工程量', '数量', '工程数量', 'qty', 'quantity'],
    'unit_rate': ['综合单价', '单价', '清单单价', '综合单价(元)', 'unit_price', 'rate'],
    'total': ['合价', '金额', '合价(元)', 'total', 'amount'],
    'provisional_sum': ['暂估价', '暂列金额', '暂估价合计', '其中:暂估价', 'provisional'],
    'project_name': ['工程名称', '工程', '单项工程', '项目名称(工程)', 'project'],
    'sub_division': ['子分部', '分部', '分项', '分部工程', 'sub_division'],
    'ordinal': ['序号', '行号', '顺序号', '编号', 'no', 'seq'],
    'source_path': ['来源路径', '路径', '文件', 'source_path'],
}

# 必填规范字段（缺失 → 整表报错终止，不静默导入垃圾数据，见 §7 匹配规则 4）
REQUIRED_CANON = ('item_name',)


def _full_to_half(s):
    """全角字符（U+FF01–FF5E）→ 半角；全角空格 → 普通空格。"""
    out = []
    for ch in s:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E:
            out.append(chr(cp - 0xFEE0))
        elif cp == 0x3000:
            out.append(' ')
        else:
            out.append(ch)
    return ''.join(out)


def normalize_header(text):
    """表头归一化：全→半、英文转小写、去所有空白。

    空 / None 返回 ''（调用方据此跳过）。
    """
    if text is None:
        return ''
    s = _full_to_half(str(text))
    s = s.lower()
    s = re.sub(r'\s+', '', s)
    return s


# 反向索引：归一化别名 → 规范字段（构建一次，模块级常量）
_CANON_BY_NORM = {}
for _canon, _aliases in ALIASES.items():
    for _alias in _aliases:
        _CANON_BY_NORM[normalize_header(_alias)] = _canon


def map_header(cell):
    """单格表头 → 规范字段名，未识别返回 None。"""
    return _CANON_BY_NORM.get(normalize_header(cell))


def map_headers(row_values):
    """解析整行表头 → (header_map, unrecognized, multi_hit)。

    header_map    : {col_index: canonical_field}   # 第一个命中列（向后兼容）
    unrecognized  : [(col_index, raw_value), ...]   # 真正未识别列，值应落入 extra(Json)
    multi_hit     : {canonical_field: [col_index, ...]}  # 所有命中同一字段的列索引（含第一个）

    匹配规则（M1 §7）：
    1. 归一化后精确匹配 → 命中；
    2. 未命中 → 进 unrecognized（不报错，值落 extra）；
    3. 多列命中同一规范字段 → 所有命中列记录在 multi_hit；header_map 取第一列，
       其余列**不进 unrecognized**（调用方用 extract_field_value() 做首个非空列回退）；
    4. 必填缺失：调用方用 validate_required() 判定是否整表终止。

    【v1.1 修复】原实现把多列命中的其余列丢进 unrecognized，导致数据提取阶段
    无法做"首个非空列"回退（首列为空时数据丢失）。现通过 multi_hit 暴露所有命中列，
    由 extract_field_value() 在数据行层面取首个非空值。
    """
    header_map = {}
    unrecognized = []
    multi_hit = {}
    for i, cell in enumerate(row_values):
        norm = normalize_header(cell)
        if not norm:
            continue
        canon = _CANON_BY_NORM.get(norm)
        if canon is None:
            unrecognized.append((i, cell))
        else:
            if canon not in multi_hit:
                multi_hit[canon] = []
                header_map[i] = canon
            multi_hit[canon].append(i)
    return header_map, unrecognized, multi_hit


def extract_field_value(row, col_indices):
    """从数据行中按列索引列表取首个非空值。

    用于多列命中同一规范字段时的回退：第一列为空时取第二列，依此类推。

    参数
    ----
    row : list/tuple  数据行（单元格值列表）
    col_indices : list[int]  命中同一规范字段的列索引列表（从 multi_hit 获取）

    返回
    ----
    首个非空（非 None、非空字符串、非纯空白）的值；全部为空返回 None。

    示例
    ----
    >>> extract_field_value(['', '电缆', None], [0, 1, 2])
    '电缆'
    >>> extract_field_value(['', None, '  '], [0, 1, 2])
    None
    """
    for idx in col_indices:
        if idx >= len(row):
            continue
        val = row[idx]
        if val is None:
            continue
        if isinstance(val, str) and val.strip() == '':
            continue
        return val
    return None


def validate_required(header_map):
    """必填规范字段是否齐全（缺失 → 返回缺失列表）。"""
    present = set(header_map.values())
    missing = [c for c in REQUIRED_CANON if c not in present]
    return missing
