# -*- coding: utf-8 -*-
"""计量单位归一化（M1 §4.7③ 落地）。

纯函数模块，**不依赖 odoo**，可被纯函数 pytest 直接 import。

规则：归一化前先去空白、全角转半角、转小写、折叠内部空白；
命中映射则写入 unit_std；**未命中则原样小写存入并打 warning**（提示补映射）。
`unit`（原始值）始终保留，不覆盖（职责边界见 §4.7③）。

映射表覆盖设计稿 §4.7③ 列出的全部同义/全半角/中英变体。
"""
import re

# 标准值 → 接受的写法（含全角、大小写、中英混排、半角括号变体）
UNIT_MAP = {
    'm': ['米', 'm', 'M', '米(m)', '延米', '延长米'],
    'kg': ['千克', 'kg', 'KG', '公斤'],
    't': ['吨', 't', 'T'],
    '㎡': ['平方米', '平米', 'm2', 'm²'],
    'm³': ['立方米', '立方', 'm3', 'm³'],
    '台': ['台'],
    '套': ['套'],
    '个': ['个'],
    '组': ['组'],
    '块': ['块'],
    '根': ['根'],
    '处': ['处'],
}


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


def _norm_text(s):
    """单位归一化预处理：全→半、转小写、折叠内部空白。"""
    if s is None:
        return ''
    s = _full_to_half(str(s))
    s = s.lower()
    s = re.sub(r'\s+', '', s)
    return s


# 反向索引：归一化后的写法 → 标准值（在 _norm_text 定义后构建，模块级常量）
_UNIT_BY_NORM = {}
for _std, _variants in UNIT_MAP.items():
    for _variant in _variants:
        _UNIT_BY_NORM[_norm_text(_variant)] = _std


def normalize_unit(unit):
    """归一化计量单位。

    返回 (unit_std, warning)：
    - 命中映射 → (标准值, False)
    - 未命中   → (原值小写, True) 并标记 warning（提示补映射）
    - 空值     → ('', False)
    """
    if unit is None:
        return ('', False)
    raw = str(unit).strip()
    if not raw:
        return ('', False)
    norm = _norm_text(raw)
    std = _UNIT_BY_NORM.get(norm)
    if std:
        return (std, False)
    # 未命中 → 原样小写存入并打 warning（§4.7③），原始 unit 不被覆盖
    return (norm, True)
