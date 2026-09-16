"""5 大类材料正则白名单分类器

不依赖 material_dict_id / 9位码映射表，直接从 item_name + item_feature 提取。
用于单价分析流水线。
"""
import re
from dataclasses import dataclass


@dataclass
class ClassifyResult:
    category: str          # 5 大类之一，或 ""
    spec: str              # 规格（如 YJV-4*120 / Φ20 / C30 / DN100）
    material_type: str     # 材质细分（如 镀锌钢管/PPR/不锈钢/普通混凝土）


# 电缆型号前缀
_CABLE_MODELS = [
    r'WDZ[AB]N?-?YJY', r'WDZ[AB]N?-?YJV', r'WDZ[AB]?-?YJY', r'WDZ[AB]?-?YJV',
    r'YJV', r'YJY', r'VV', r'VV22',
    r'ZR-YJV', r'ZR-YJY', r'NH-YJV', r'NH-YJY', r'ZRC-YJV', r'ZRC-YJY',
    r'BTLY', r'NG-A', r'BTTW', r'矿物绝缘', r'矿物电缆',
    r'BV', r'BVR', r'RVV', r'RVVP', r'BVVB',
    r'控制电缆', r'电力电缆', r'布电线',
]

# 钢筋
_REBAR_PAT = re.compile(
    r'(HRB400|HRB500|HPB300|HRBF400|螺纹钢|圆钢|钢筋)\s*[ΦφA]?\s*(\d{1,3})?',
    re.IGNORECASE,
)

# 混凝土强度
_CONCRETE_PAT = re.compile(r'\b(C\d{2}(?:\.\d)?)\b')

# 水泥
_CEMENT_PAT = re.compile(
    r'(P\.O\s*\d{3}|P\.C\s*\d{3}|P\.I\s*\d{3}|P\.II\s*\d{3}|硅酸盐水泥|普通水泥|矿渣水泥|快硬|白水泥|水泥)',
    re.IGNORECASE,
)

# 管道
_PIPE_PAT = re.compile(
    r'(镀锌钢管|焊接钢管|无缝钢管|不锈钢管|螺旋焊管|直缝焊管|'
    r'PPR[- ]?管?|PVC[- ]?U?管?|HDPE[- ]?管?|PE[- ]?RT?管?|UPVC|PP管|'
    r'铸铁管|球墨铸铁管|铝塑复合管|铜管|'
    r'给水管|排水管|雨水管|采暖管|燃气管道|'
    r'DN\s*\d+|de\s*\d+)',
    re.IGNORECASE,
)

# 电缆规格（截面）
_CABLE_SECTION_PAT = re.compile(
    r'(\d+\s*[×x*]\s*\d+(?:\s*[+]\s*\d+\s*[×x*]\s*\d+)?(?:\s*mm2?)?)',
    re.IGNORECASE,
)


def _extract_cable_spec(text: str) -> str:
    """从文本提取电缆型号+截面"""
    model = ""
    # 先找型号前缀（WDZA-YJY/BTLY/BV/YJV 等）
    for pat in _CABLE_MODELS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            model = m.group(0).upper().replace(" ", "")
            break
    sec = _CABLE_SECTION_PAT.search(text)
    if sec:
        sec_str = sec.group(1).replace(" ", "").replace("×", "*").replace("x", "*")
        # 去掉 mm2/mm
        sec_str = re.sub(r'mm2?$', '', sec_str, flags=re.IGNORECASE)
        if model:
            return f"{model}-{sec_str}"
        return sec_str
    return model or "电缆"


def _extract_rebar_spec(text: str) -> str:
    m = _REBAR_PAT.search(text)
    if m:
        grade = m.group(1) or "钢筋"
        dia = m.group(2)
        if dia:
            return f"{grade} Φ{dia}"
        return grade
    return "钢筋"


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


def _extract_pipe_spec(text: str) -> str:
    m = _PIPE_PAT.search(text)
    if m:
        material = m.group(0)
        # 去掉 material 里已有的 DN/de 部分，避免 "DN50 DN50" 重复
        material = re.sub(r'\s*(DN|de)\s*\d+\s*$', '', material, flags=re.IGNORECASE).strip()
        dn = re.search(r'(DN|de)\s*(\d+)', text, re.IGNORECASE)
        if dn:
            dn_str = f"{dn.group(1).upper()}{dn.group(2)}"
            return f"{material} {dn_str}" if material else dn_str
        return material
    return "管道"


def classify_boq(name: str, feature: str) -> ClassifyResult:
    """对单条 boq_item 分类。name=item_name, feature=item_feature"""
    text = f"{name or ''} {feature or ''}"

    # 排除桥架：只看 item_name（feature 里"沿桥架敷设"不算桥架材料）
    is_tray = bool(re.search(r'桥架|托盘|梯架|线槽', name or '', re.IGNORECASE))

    # 1. 混凝土（优先，因为 "C25" 特征明显）
    if _CONCRETE_PAT.search(text) or re.search(r'\b(混凝土|砼)\b', text):
        # 排除 "电缆桥架" 等
        if not is_tray:
            return ClassifyResult(
                category="混凝土",
                spec=_extract_concrete_spec(text),
                material_type="普通混凝土",
            )

    # 2. 水泥
    if _CEMENT_PAT.search(text) and not re.search(r'混凝土', text):
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

    # 4. 电缆（排除桥架）
    if not is_tray:
        for pat in _CABLE_MODELS:
            if re.search(pat, text, re.IGNORECASE):
                return ClassifyResult(
                    category="电线电缆",
                    spec=_extract_cable_spec(text),
                    material_type="电力电缆",
                )

    # 5. 管道
    if _PIPE_PAT.search(text):
        return ClassifyResult(
            category="管道",
            spec=_extract_pipe_spec(text),
            material_type="管道",
        )

    return ClassifyResult(category="", spec="", material_type="")
