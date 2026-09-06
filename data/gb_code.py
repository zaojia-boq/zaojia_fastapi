# -*- coding: utf-8 -*-
"""国标清单编码解析 + 同类项聚合键（M1 §4.3② / §4.7② 落地）。

纯函数模块，**不依赖 odoo**，可被纯函数 pytest 直接 import。

能力：
- parse_gb_code(code)      → (code_9, code_full)
    处理 12/11/9/10(异常映射)/Z前缀/未知 六类；code_9 用于匹配，code_full 写 item_code；
    原始值由调用方保留在 item_code_raw（分离见 §4.3）。
- is_valid_gb_code(code)   → bool（9 位纯数字国标码）
- compute_match_key(...)   → (match_key, source)
    优先级 dict > std > Z前缀 > 有效国标码 > raw，且**显式带入版本维度**（F1）
    与 Z 前缀强制 2024（F3），杜绝 2013/2024 跨版本同码误聚合。

设计审定：F1（版本维度）/ F2（10 位异常裁决）/ F3（Z 前缀）均来自 M1模块设计.md §4.7②。
"""
import re

# 已知 10 位异常编码（规范文件录入错误，多一位 0）→ 修正为 9 位（§4.7② F2 裁决）。
# 经核对 2013/2024 规范文件：仅以下 2 例；未发现的 10 位一律原值入库 + warning，匹配退化为 raw。
GB_CODE_10D_ANOMALIES = {
    '0302280006': '030228006',   # 重整器
    '0304130010': '030413010',   # 小区路灯
}


def is_valid_gb_code(code):
    """判定是否为合法 9 位纯数字国标编码。"""
    if not code:
        return False
    return len(code) == 9 and code.isdigit()


def parse_gb_code(code):
    """解析国标编码，返回 (code_9, code_full) 元组。

    code_9   : 用于匹配的 9 位（或 Z 键 / 原值）；空编码返回 ('', '')
    code_full: 规范化后的完整值（9/12/修正后9/Z键/原值），写入 item_code；
               原始字符串始终在 item_code_raw 保留（溯源见 §4.3②）
    """
    code = '' if code is None else str(code).strip()
    if not code:
        return ('', '')

    # 情况1：12 位编码 → 截取前 9 位，完整保留
    if len(code) == 12 and code.isdigit():
        return (code[:9], code)

    # 情况2：11 位编码 → 可能是 12 位丢失前导 0 → 补前导 0 → 截取前 9 位
    if len(code) == 11 and code.isdigit() and code[0] != '0':
        code_padded = '0' + code
        return (code_padded[:9], code_padded)

    # 情况3：9 位编码 → 直接使用
    if len(code) == 9 and code.isdigit():
        return (code, code)

    # 情况4：10 位编码 → 规范文件录入错误（多一位 0）
    #   F2 裁决：已知异常 → 按映射修正为 9 位；未知 → 原值入库 + warning，匹配退化为 raw
    if len(code) == 10 and code.isdigit():
        if code in GB_CODE_10D_ANOMALIES:
            corrected = GB_CODE_10D_ANOMALIES[code]   # 修正为 9 位
            return (corrected, corrected)             # item_code 存 9 位，原 10 位留 item_code_raw
        return (code, code)                          # 原值入库，匹配时 is_valid_gb_code 失败 → raw

    # 情况5：2024 版总图工程编码（Z 前缀，自定义规则，非 9 位纯数字国标码）
    #   F3：归一化键 = 'Z' + 后续大写字符；version 由 compute_match_key 强制 2024
    if code.upper().startswith('Z'):
        norm = 'Z' + code[1:].strip().upper()
        return (norm, norm)

    # 情况6：其他（自定义编码、含字母等）→ 原样返回，不匹配编码规则
    return (code, code)


def _norm(s):
    """名称/特征归一化：去空白、转小写，用于 raw 兜底键（M1 §4.7② 兜底分支）。"""
    if s is None:
        return ''
    return re.sub(r'\s+', '', str(s).strip().lower())


def compute_match_key(item_code='', item_name='', item_feature='', unit_std='',
                      std_name='', std_spec='', material_dict_id=None,
                      item_code_version='unknown'):
    """计算同类项聚合键（M1 §4.7②）。

    入参说明：
    - item_code / item_name / item_feature / item_code_version：来自 boq_item 对应字段；
    - unit_std：已归一化单位（由 unit_normalize.normalize_unit 在导入期写入，A 类可重建）；
    - std_name / std_spec：标准化字段（B 类，人工确认后才有）；
    - material_dict_id：传入字典记录 id（int）即可，无需完整 M2O 对象。

    返回 (match_key, source)，source ∈ {dict, std, code, raw}。
    优先级与版本维度（F1/F2/F3）严格按设计稿：
      1. 有物料字典 → dict（最高优先级，人工标注最可靠）
      2. 已标准化名称+规格 → std
      3. Z 前缀编码 → code:2024:Z<键>（强制 2024）
      4. 有效 9 位国标码 → code:{ver}:{code_9}（带入版本维度，2013 与 2024 不同键）
      5. 兜底 → raw:{ver}:{norm(name)}|{norm(feature)}|{unit_std}
    """
    code_9, _ = parse_gb_code(item_code)
    ver = item_code_version or 'unknown'

    if material_dict_id:                              # 1. 物料字典（人工标注，最可靠）
        return (f"dict:{material_dict_id}|{unit_std}", 'dict')
    if std_name and std_spec:                        # 2. 标准化名称 + 规格
        return (f"std:{std_name}|{std_spec}|{unit_std}", 'std')
    if code_9 and code_9[0] == 'Z':                  # 3. Z 前缀（F3：强制 2024）
        return (f"code:2024:{code_9}|{unit_std}", 'code')
    if is_valid_gb_code(code_9):                     # 4. 有效国标 9 位（F1：带版本维度）
        return (f"code:{ver}:{code_9}|{unit_std}", 'code')
    # 5. 兜底：名称聚合也带入版本维度（F1）
    return (f"raw:{ver}:{_norm(item_name)}|{_norm(item_feature)}|{unit_std}", 'raw')
