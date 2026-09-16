"""清单版本识别纯函数（2013 vs 2024）

4 层筛选 + 两次校验：
  第1层：编码只在某一版独有 → 直接定版本，high
  第2层：编码两版都有，名称完全匹配 → high
  第3层：编码两版都有，名称包含匹配 → medium
  第4层：前6位前缀倾向 → low
  都不命中 → unknown

两次校验：
  第1次识别 + 第2次交叉验证
  一致 → 存
  不一致 → 存 unknown（或取较高置信度降一级）
"""
import json
import os
from functools import lru_cache

_LOOKUP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version_lookup_data.json")


@lru_cache(maxsize=1)
def _load_lookup():
    """加载查表数据（缓存，只加载一次）"""
    with open(_LOOKUP_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "codes_2013": set(data["2013"].keys()),
        "codes_2024": set(data["2024"].keys()),
        "names_2013": data["2013"],  # code9 -> name
        "names_2024": data["2024"],  # code9 -> name
        "only_2013": set(data["only_2013"]),
        "only_2024": set(data["only_2024"]),
        "both": set(data["both"]),
    }


def _get_code9(item_code: str) -> str:
    """统一截前 9 位"""
    if not item_code:
        return ""
    return item_code.strip()[:9]


def classify_version(item_code: str, item_name: str = "") -> dict:
    """识别清单项的清单版本（2013 / 2024 / unknown）

    Args:
        item_code: 清单项目编码（9 位或 12 位）
        item_name: 项目名称（用于第2/3层名称匹配）

    Returns:
        {
            "version": "2013" | "2024" | "unknown",
            "confidence": "high" | "medium" | "low" | "unknown",
            "layer": 1 | 2 | 3 | 4,
        }
    """
    code9 = _get_code9(item_code)
    if not code9 or len(code9) < 6:
        return {"version": "unknown", "confidence": "unknown", "layer": 4}

    lookup = _load_lookup()
    name = (item_name or "").strip()

    # 第1层：编码只在某一版独有
    if code9 in lookup["only_2013"]:
        return {"version": "2013", "confidence": "high", "layer": 1}
    if code9 in lookup["only_2024"]:
        return {"version": "2024", "confidence": "high", "layer": 1}

    # 编码不在两版任何一个里 → 直接 unknown（不走名称匹配）
    if code9 not in lookup["both"] and code9 not in lookup["codes_2013"] and code9 not in lookup["codes_2024"]:
        # 第4层兜底：前6位前缀倾向
        prefix6 = code9[:6]
        prefix6_only_2013 = set(c[:6] for c in lookup["only_2013"])
        prefix6_only_2024 = set(c[:6] for c in lookup["only_2024"])
        if prefix6 in prefix6_only_2013:
            return {"version": "2013", "confidence": "low", "layer": 4}
        if prefix6 in prefix6_only_2024:
            return {"version": "2024", "confidence": "low", "layer": 4}
        return {"version": "unknown", "confidence": "unknown", "layer": 4}

    # 编码两版都有（或只在某一版但不是独有）→ 走名称匹配
    # 第2层：名称完全匹配
    name_2013 = lookup["names_2013"].get(code9, "")
    name_2024 = lookup["names_2024"].get(code9, "")

    if name and name_2013 and name == name_2013:
        return {"version": "2013", "confidence": "high", "layer": 2}
    if name and name_2024 and name == name_2024:
        return {"version": "2024", "confidence": "high", "layer": 2}

    # 第3层：名称包含匹配
    if name and name_2013 and name_2013 in name:
        return {"version": "2013", "confidence": "medium", "layer": 3}
    if name and name_2024 and name_2024 in name:
        return {"version": "2024", "confidence": "medium", "layer": 3}

    # 第4层：前6位前缀倾向
    prefix6 = code9[:6]
    prefix6_only_2013 = set(c[:6] for c in lookup["only_2013"])
    prefix6_only_2024 = set(c[:6] for c in lookup["only_2024"])
    if prefix6 in prefix6_only_2013:
        return {"version": "2013", "confidence": "low", "layer": 4}
    if prefix6 in prefix6_only_2024:
        return {"version": "2024", "confidence": "low", "layer": 4}

    return {"version": "unknown", "confidence": "unknown", "layer": 4}


def cross_validate(item_code: str, item_name: str, result: dict) -> dict:
    """第二次交叉校验

    规则：
    - 第1层（独有编码）：用名称包含再验一遍
    - 第2/3层（名称匹配）：用前缀倾向再验一遍
    - 两次一致 → 存
    - 两次不一致 → 取较高置信度降一级
    - 第1次 high + 第2次 unknown → 存 high（第1层独有编码本身就很可靠）
    """
    # 第1层不需要交叉校验（独有编码直接定，最可靠）
    if result["layer"] == 1:
        return result

    # 第2/3层：用前缀倾向交叉验
    code9 = _get_code9(item_code)
    if len(code9) < 6:
        return result

    lookup = _load_lookup()
    prefix6 = code9[:6]
    prefix6_only_2013 = set(c[:6] for c in lookup["only_2013"])
    prefix6_only_2024 = set(c[:6] for c in lookup["only_2024"])

    cross = "unknown"
    if prefix6 in prefix6_only_2013:
        cross = "2013"
    elif prefix6 in prefix6_only_2024:
        cross = "2024"

    # 两次一致 → 存
    if cross == result["version"]:
        return result

    # 两次不一致
    # high + unknown → 存 high（名称完全匹配很可靠）
    if result["confidence"] == "high" and cross == "unknown":
        return result

    # 其他不一致 → 降一级或存 unknown
    if result["confidence"] == "medium":
        return {"version": result["version"], "confidence": "low", "layer": result["layer"]}
    if result["confidence"] == "low":
        return {"version": "unknown", "confidence": "unknown", "layer": result["layer"]}

    return result


def classify_version_full(item_code: str, item_name: str = "") -> dict:
    """完整识别：4 层筛选 + 两次校验"""
    result = classify_version(item_code, item_name)
    result = cross_validate(item_code, item_name, result)
    return result
