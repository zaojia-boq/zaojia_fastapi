"""5 大类材料分类器 v3：前缀初筛 + 大类专用正则提规格

v5 架构：
  第1步：读 item_code_version（已由任务1.1预填）
  第2步：前6位白名单初筛定大类
  第3步：前9位排除项过滤
  第4步：大类专用正则提规格

不传 item_code 时走 v2 纯文本正则兜底（兼容旧调用）。
"""
import re
from dataclasses import dataclass


@dataclass
class ClassifyResult:
    category: str
    spec: str
    material_type: str


# LRU 缓存
_CLASSIFY_CACHE: dict = {}
_CLASSIFY_CACHE_MAX = 100_000


def _classify_cache_put(key, result):
    if len(_CLASSIFY_CACHE) >= _CLASSIFY_CACHE_MAX:
        for k in list(_CLASSIFY_CACHE.keys())[: _CLASSIFY_CACHE_MAX // 2]:
            _CLASSIFY_CACHE.pop(k, None)
    _CLASSIFY_CACHE[key] = result


# ===== 前缀白名单表（v5 新增）=====
# 前6位 → 大类
# 前9位排除项（不是该大类本体）

PREFIX_WHITELIST_2013 = {
    "030408": {"category": "电线电缆", "exclude_codes": {"030408006", "030408007"}},
    "030412": {"category": "配管配线", "exclude_codes": {"030412003"}},
    "010515": {"category": "钢筋", "exclude_codes": set()},
    "010502": {"category": "混凝土", "exclude_codes": set()},
}

PREFIX_WHITELIST_2024 = {
    "030409": {"category": "电线电缆", "exclude_codes": {"030409003", "030409004", "030409005"}},
    "030412": {"category": "配管配线", "exclude_codes": {"030412003"}},
    "031001": {"category": "管道", "exclude_codes": {"031001010"}},
    "010506": {"category": "钢筋", "exclude_codes": set()},
    "010502": {"category": "混凝土", "exclude_codes": set()},
}

# 水泥没有明确前缀（散在多个前缀里），走纯文本正则兜底


# ===== 大类专用正则提规格 =====

# 电缆型号前缀
_CABLE_MODELS_ORDERED = [
    (r'BTLY|NG-A|BTTW|矿物绝缘|矿物电缆', 'BTLY'),
    (r'WDZ[AB]N?-?YJY', 'YJY'),
    (r'WDZ[AB]N?-?YJV', 'YJV'),
    (r'ZR-?YJV|ZRC?-?YJV|ZRN?-?YJV', 'YJV'),
    (r'ZR-?YJY|ZRC?-?YJY|ZRN?-?YJY', 'YJY'),
    (r'NH-?YJV', 'NH-YJV'),
    (r'NH-?YJY', 'NH-YJY'),
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

_CABLE_EXCLUDE = re.compile(
    r'(电缆头|终端头|中间头|接线端子|电缆终端|电力电缆头|控制电缆头)',
    re.IGNORECASE,
)

_REBAR_PAT = re.compile(
    r'(HRB400|HRB500|HPB300|HRBF400|螺纹钢|圆钢|钢筋)',
    re.IGNORECASE,
)
_REBAR_DIA_PAT = re.compile(r'[Φφ]\s*(\d{1,3})')

_CONCRETE_PAT = re.compile(r'\b(C\d{2}(?:\.\d)?)\b')

_CEMENT_PAT = re.compile(
    r'(P\.O\s*\d{3}|P\.C\s*\d{3}|P\.I\s*\d{3}|P\.II\s*\d{3}|'
    r'硅酸盐水泥|普通硅酸盐水泥|矿渣硅酸盐水泥|白水泥)',
    re.IGNORECASE,
)
_CEMENT_EXCLUDE = re.compile(
    r'(砂浆|楼地面|砖基础|块料|石材|擦缝|勾缝|抹灰|找平|垫层|防水|堵漏|混凝土)',
    re.IGNORECASE,
)

_PIPE_PAT = re.compile(
    r'(镀锌钢管|焊接钢管|无缝钢管|不锈钢管|螺旋焊管|直缝焊管|'
    r'PPR[- ]?管?|PVC[- ]?U?管?|CPVC[- ]?管?|HDPE[- ]?管?|PE[- ]?RT?管?|UPVC|PP管|'
    r'铸铁管|球墨铸铁管|铝塑复合管|铜管|'
    r'给水管|排水管|雨水管|采暖管|燃气管道|'
    r'DN\s*\d+|de\s*\d+|DE\s*\d+)',
    re.IGNORECASE,
)
_PIPE_EXCLUDE = re.compile(
    r'(截止阀|闸阀|球阀|蝶阀|止回阀|排气阀|安全阀|减压阀|低压螺纹阀门|'
    r'管件|套管|地漏|法兰|弯头|三通|接头|堵头|'
    r'栏杆|爬梯|扶手|支架|支吊架|'
    r'一般填料|防水套管|绝热|凿|预留洞|雨水斗|散流器|风口)',
    re.IGNORECASE,
)

_CABLE_SECTION_PAT = re.compile(
    r'(\d+\s*[×x*]\s*\d+(?:\s*[+]\s*\d+\s*[×x*]\s*\d+)?(?:\s*mm2?)?)',
    re.IGNORECASE,
)


# ===== 大类专用规格提取 =====

def _extract_cable_spec(name: str, feature: str) -> str:
    text = f"{name or ''} {feature or ''}"
    if _CABLE_EXCLUDE.search(text):
        return ""
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
    if _PIPE_EXCLUDE.search(text):
        return ""
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


# ===== v5 前缀初筛主入口 =====

def _classify_by_prefix(item_code: str, version: str, name: str, feature: str) -> ClassifyResult | None:
    """v5 前缀初筛：前6位白名单 → 前9位排除 → 大类专用正则提规格

    返回 None 表示不在白名单里，走纯文本兜底。
    """
    if not item_code or len(item_code) < 6:
        return None

    prefix6 = item_code[:6]
    prefix9 = item_code[:9]

    # 选对应版本的白名单
    if version == "2013":
        whitelist = PREFIX_WHITELIST_2013
    elif version == "2024":
        whitelist = PREFIX_WHITELIST_2024
    else:
        # unknown 版本：两个表都查，命中哪个算哪个
        whitelist = {**PREFIX_WHITELIST_2013, **PREFIX_WHITELIST_2024}

    if prefix6 not in whitelist:
        return None

    entry = whitelist[prefix6]
    category = entry["category"]

    # 前9位排除项过滤
    if prefix9 in entry["exclude_codes"]:
        return None

    # 大类专用正则提规格
    if category == "电线电缆":
        spec = _extract_cable_spec(name, feature)
        if not spec:
            return ClassifyResult(category="电线电缆", spec="电线电缆(未识别)", material_type="电力电缆")
        return ClassifyResult(category="电线电缆", spec=spec, material_type="电力电缆")

    elif category == "钢筋":
        spec = _extract_rebar_spec(f"{name or ''} {feature or ''}")
        return ClassifyResult(category="钢筋", spec=spec, material_type="钢筋")

    elif category == "混凝土":
        spec = _extract_concrete_spec(f"{name or ''} {feature or ''}")
        return ClassifyResult(category="混凝土", spec=spec, material_type="普通混凝土")

    elif category == "管道":
        spec = _extract_pipe_spec(name, feature)
        if not spec:
            return ClassifyResult(category="管道", spec="管道(未识别)", material_type="管道")
        return ClassifyResult(category="管道", spec=spec, material_type="管道")

    elif category == "配管配线":
        # 配管：SC/PC/JDG + 规格
        text = f"{name or ''} {feature or ''}"
        sc_m = re.search(r'(SC|PC|JDG|KBG)\s*(\d+)', text, re.IGNORECASE)
        if sc_m:
            key = sc_m.group(1).upper()
            size = sc_m.group(2)
            return ClassifyResult(category="配管配线", spec=f"{key}{size}", material_type="配管")
        return ClassifyResult(category="配管配线", spec="配管(未识别)", material_type="配管")

    return None


# ===== v2 纯文本兜底（水泥走这里，其他大类前缀没命中也走这里）=====

def _classify_by_text(name: str, feature: str) -> ClassifyResult:
    """v2 纯文本正则兜底"""
    text = f"{name or ''} {feature or ''}"
    is_tray = bool(re.search(r'桥架|托盘|梯架|线槽', name or '', re.IGNORECASE))

    # 混凝土
    if _CONCRETE_PAT.search(text) or re.search(r'\b(混凝土|砼)\b', text):
        if not is_tray:
            return ClassifyResult(
                category="混凝土",
                spec=_extract_concrete_spec(text),
                material_type="普通混凝土",
            )

    # 水泥
    if _CEMENT_PAT.search(text) and not re.search(r'混凝土', text) and not _CEMENT_EXCLUDE.search(text):
        return ClassifyResult(
            category="水泥",
            spec=_extract_cement_spec(text),
            material_type="水泥",
        )

    # 钢筋
    if _REBAR_PAT.search(text) and not is_tray:
        return ClassifyResult(
            category="钢筋",
            spec=_extract_rebar_spec(text),
            material_type="钢筋",
        )

    # 电缆
    if not is_tray:
        spec = _extract_cable_spec(name, feature)
        if spec:
            return ClassifyResult(
                category="电线电缆",
                spec=spec,
                material_type="电力电缆",
            )

    # 管道
    spec = _extract_pipe_spec(name, feature)
    if spec:
        return ClassifyResult(
            category="管道",
            spec=spec,
            material_type="管道",
        )

    return ClassifyResult(category="", spec="", material_type="")


# ===== 主入口 =====

def classify_boq(name: str, feature: str, item_code: str = "", item_code_version: str = "") -> ClassifyResult:
    """v3 分类器：前缀初筛优先，纯文本兜底

    Args:
        name: 项目名称
        feature: 项目特征
        item_code: 清单编码（v5 新增，用于前缀初筛）
        item_code_version: 清单版本（v5 新增，"2013"/"2024"/"unknown"）
    """
    key = (name or '', feature or '', item_code or '', item_code_version or '')
    cached = _CLASSIFY_CACHE.get(key)
    if cached is not None:
        return ClassifyResult(cached.category, cached.spec, cached.material_type)

    result = _classify_boq_impl(name, feature, item_code, item_code_version)
    _classify_cache_put(key, result)
    return ClassifyResult(result.category, result.spec, result.material_type)


def _classify_boq_impl(name: str, feature: str, item_code: str = "", item_code_version: str = "") -> ClassifyResult:
    # v5 前缀初筛
    if item_code and item_code_version:
        prefix_result = _classify_by_prefix(item_code, item_code_version, name, feature)
        if prefix_result is not None:
            return prefix_result

    # v2 纯文本兜底
    return _classify_by_text(name, feature)
