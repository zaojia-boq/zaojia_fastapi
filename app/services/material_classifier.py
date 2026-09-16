"""5 大类材料正则白名单分类器（v2 系统修复版）

修复点：
1. 电缆型号归一化：WDZA/WDZAN/WDZR/WDZRN 阻燃后缀统一去掉，同型号合并
2. 电缆排除：电缆头/终端头/接线端子不算电缆本体
3. 水泥收紧：只认 PO/PC/PI/PII + 强度等级，排除砂浆/楼地面/砖基础/擦缝
4. 管道排除：阀门/管件/套管/地漏/栏杆/爬梯不算管道
5. 钢筋无直径归"钢筋(无直径)"
"""
import re
from dataclasses import dataclass


@dataclass
class ClassifyResult:
    category: str
    spec: str
    material_type: str


# P1-2 优化：模块级 LRU 缓存（dict 实现，进程内安全；单价分析逐行调用重复率高）。
# 上限 100k，避免内存无界增长；FIFO 淘汰策略足够（清单项名称多样性有限）。
_CLASSIFY_CACHE: dict = {}
_CLASSIFY_CACHE_MAX = 100_000


def _classify_cache_put(key, result):
    if len(_CLASSIFY_CACHE) >= _CLASSIFY_CACHE_MAX:
        # 简单 FIFO：清除最早一半
        for k in list(_CLASSIFY_CACHE.keys())[: _CLASSIFY_CACHE_MAX // 2]:
            _CLASSIFY_CACHE.pop(k, None)
    _CLASSIFY_CACHE[key] = result


# 电缆型号前缀（按优先级排序，短的放后面避免误匹配）
_CABLE_MODELS_ORDERED = [
    # 矿物电缆
    (r'BTLY|NG-A|BTTW|矿物绝缘|矿物电缆', 'BTLY'),
    # 阻燃/耐火前缀归一化：WDZA-YJY / WDZAN-YJY / WDZR-YJY / WDZRN-YJY → YJY
    (r'WDZ[AB]N?-?YJY', 'YJY'),
    (r'WDZ[AB]N?-?YJV', 'YJV'),
    (r'ZR-?YJV|ZRC?-?YJV|ZRN?-?YJV', 'YJV'),
    (r'ZR-?YJY|ZRC?-?YJY|ZRN?-?YJY', 'YJY'),
    (r'NH-?YJV', 'NH-YJV'),
    (r'NH-?YJY', 'NH-YJY'),
    # 普通型号
    (r'YJV', 'YJV'),
    (r'YJY', 'YJY'),
    (r'VV22', 'VV22'),
    (r'VV', 'VV'),
    (r'BVVB', 'BVVB'),
    (r'BV', 'BV'),
    (r'BVR', 'BVR'),
    (r'RVV', 'RVV'),
    (r'RVVP', 'RVVP'),
]

# 电缆排除项（不是电缆本体）
_CABLE_EXCLUDE = re.compile(
    r'(电缆头|终端头|中间头|接线端子|电缆终端|电力电缆头|控制电缆头)',
    re.IGNORECASE,
)

# 钢筋
_REBAR_PAT = re.compile(
    r'(HRB400|HRB500|HPB300|HRBF400|螺纹钢|圆钢|钢筋)',
    re.IGNORECASE,
)
_REBAR_DIA_PAT = re.compile(r'[Φφ]\s*(\d{1,3})')

# 混凝土强度
_CONCRETE_PAT = re.compile(r'\b(C\d{2}(?:\.\d)?)\b')

# 水泥（收紧：只认通用水泥型号+强度等级）
_CEMENT_PAT = re.compile(
    r'(P\.O\s*\d{3}|P\.C\s*\d{3}|P\.I\s*\d{3}|P\.II\s*\d{3}|'
    r'硅酸盐水泥|普通硅酸盐水泥|矿渣硅酸盐水泥|白水泥)',
    re.IGNORECASE,
)
# 水泥排除项（工序/构件不是水泥材料）
_CEMENT_EXCLUDE = re.compile(
    r'(砂浆|楼地面|砖基础|块料|石材|擦缝|勾缝|抹灰|找平|垫层|防水|堵漏|混凝土)',
    re.IGNORECASE,
)

# 管道
_PIPE_PAT = re.compile(
    r'(镀锌钢管|焊接钢管|无缝钢管|不锈钢管|螺旋焊管|直缝焊管|'
    r'PPR[- ]?管?|PVC[- ]?U?管?|CPVC[- ]?管?|HDPE[- ]?管?|PE[- ]?RT?管?|UPVC|PP管|'
    r'铸铁管|球墨铸铁管|铝塑复合管|铜管|'
    r'给水管|排水管|雨水管|采暖管|燃气管道|'
    r'DN\s*\d+|de\s*\d+|DE\s*\d+)',
    re.IGNORECASE,
)
# 管道排除项（阀门/管件/套管/地漏/栏杆/爬梯/绝热/凿槽/预留洞）
_PIPE_EXCLUDE = re.compile(
    r'(截止阀|闸阀|球阀|蝶阀|止回阀|排气阀|安全阀|减压阀|低压螺纹阀门|'
    r'管件|套管|地漏|法兰|弯头|三通|接头|堵头|'
    r'栏杆|爬梯|扶手|支架|支吊架|'
    r'一般填料|防水套管|绝热|凿|预留洞|雨水斗|散流器|风口)',
    re.IGNORECASE,
)

# 电缆规格（截面）
_CABLE_SECTION_PAT = re.compile(
    r'(\d+\s*[×x*]\s*\d+(?:\s*[+]\s*\d+\s*[×x*]\s*\d+)?(?:\s*mm2?)?)',
    re.IGNORECASE,
)


def _extract_cable_spec(name: str, feature: str) -> str:
    text = f"{name or ''} {feature or ''}"
    if _CABLE_EXCLUDE.search(text):
        return ""
    # 必须是电缆/电线/配线条目（配电箱尺寸/GRC线条/灯具尺寸不算）
    if not re.search(r'电缆|电线|配线|布电线', name or '', re.IGNORECASE):
        return ""
    model = ""
    for pat, norm in _CABLE_MODELS_ORDERED:
        if re.search(pat, text, re.IGNORECASE):
            model = norm
            break
    sec = _CABLE_SECTION_PAT.search(text)
    if sec:
        sec_str = sec.group(1).replace(" ", "").replace("×", "*").replace("x", "*")
        sec_str = re.sub(r'mm2?$', '', sec_str, flags=re.IGNORECASE)
        if model:
            return f"{model}-{sec_str}"
        return sec_str
    return model or ""


def _extract_rebar_spec(text: str) -> str:
    m = _REBAR_PAT.search(text)
    grade = m.group(1) if m else "钢筋"
    dm = _REBAR_DIA_PAT.search(text)
    if dm:
        return f"{grade} Φ{dm.group(1)}"
    return f"{grade}(无直径)"


def _extract_concrete_spec(text: str) -> str:
    m = _CONCRETE_PAT.search(text)
    if m:
        return m.group(1).upper()
    return "混凝土"


def _extract_cement_spec(text: str) -> str:
    m = _CEMENT_PAT.search(text)
    if m:
        return m.group(1).upper().replace(" ", "")
    return "水泥"


def _extract_pipe_spec(name: str, feature: str) -> str:
    text = f"{name or ''} {feature or ''}"
    # 排除阀门/管件/套管等
    if _PIPE_EXCLUDE.search(text):
        return ""
    # 线管场景：SC25/SC20 转 DN25/DN20
    is_conduit = bool(re.search(r'穿线|线管|配管', name or '', re.IGNORECASE))
    sc_m = re.search(r'SC\s*(\d+)', text, re.IGNORECASE)
    if is_conduit and sc_m:
        return f"焊接钢管 DN{sc_m.group(1)}"
    m = _PIPE_PAT.search(text)
    if m:
        material = m.group(0)
        material = re.sub(r'\s*(DN|de|DE)\s*\d+\s*$', '', material, flags=re.IGNORECASE).strip()
        dn = re.search(r'(DN|de|DE)\s*(\d+)', text, re.IGNORECASE)
        if dn:
            dn_str = f"{dn.group(1).upper()}{dn.group(2)}"
            return f"{material} {dn_str}" if material else dn_str
        return material
    return ""


def classify_boq(name: str, feature: str) -> ClassifyResult:
    """P1-2 优化：lru_cache 记忆化，相同 (name, feature) 重复调用直接命中缓存。

    单价分析路径对同一清单项逐行调 classify_boq，百万行时重复 (name, feature)
    占比高，记忆化可消除大量重复正则开销。
    """
    key = (name or '', feature or '')
    cached = _CLASSIFY_CACHE.get(key)
    if cached is not None:
        return ClassifyResult(cached.category, cached.spec, cached.material_type)
    result = _classify_boq_impl(name, feature)
    _classify_cache_put(key, result)
    return ClassifyResult(result.category, result.spec, result.material_type)


def _classify_boq_impl(name: str, feature: str) -> ClassifyResult:
    text = f"{name or ''} {feature or ''}"
    is_tray = bool(re.search(r'桥架|托盘|梯架|线槽', name or '', re.IGNORECASE))

    # 1. 混凝土
    if _CONCRETE_PAT.search(text) or re.search(r'\b(混凝土|砼)\b', text):
        if not is_tray:
            return ClassifyResult(
                category="混凝土",
                spec=_extract_concrete_spec(text),
                material_type="普通混凝土",
            )

    # 2. 水泥（收紧：排除砂浆/楼地面/砖基础等工序）
    if _CEMENT_PAT.search(text) and not re.search(r'混凝土', text) and not _CEMENT_EXCLUDE.search(text):
        return ClassifyResult(
            category="水泥",
            spec=_extract_cement_spec(text),
            material_type="水泥",
        )

    # 3. 钢筋
    if _REBAR_PAT.search(text) and not is_tray:
        return ClassifyResult(
            category="钢筋",
            spec=_extract_rebar_spec(text),
            material_type="钢筋",
        )

    # 4. 电缆（排除桥架和电缆头）
    if not is_tray:
        spec = _extract_cable_spec(name, feature)
        if spec:
            return ClassifyResult(
                category="电线电缆",
                spec=spec,
                material_type="电力电缆",
            )

    # 5. 管道（排除阀门/管件/套管）
    spec = _extract_pipe_spec(name, feature)
    if spec:
        return ClassifyResult(
            category="管道",
            spec=spec,
            material_type="管道",
        )

    return ClassifyResult(category="", spec="", material_type="")
