# -*- coding: utf-8 -*-
"""物料匹配纯评分模块（M3 §5.3 / §5.5 / §5.6 落地）。

**纯函数 · 不依赖 odoo**，可被纯函数 pytest 直接 import（与 data/gb_code.py
同模式：pure_tests 经 importlib 按文件加载，避免触发 zaojia_boq 包）。

能力：
- score_candidates(query_name, query_spec, dict_rows) -> list[dict]
    对候选字典行做 rapidfuzz 名称/规格模糊匹配，按类目层级加权，
    返回按 score 降序的候选列表（含 dict_id/name/spec/score/category_path）。
- high_confidence(candidates) -> bool
    高置信判据（M3 §5.6）：Top-1 score >= HIGH_CONF_SCORE 且 (Top-1 - Top-2) > HIGH_CONF_GAP。

阈值常量（2026-09-07 优化：从 98/10 降至 90/15，提升自动确认率）：
- HIGH_CONF_SCORE = 90.0：Top-1 分数门槛
- HIGH_CONF_GAP = 15.0：Top-1 与 Top-2 分差门槛
- NAME_WEIGHT = 0.7：名称相似度权重
- SPEC_WEIGHT = 0.3：规格相似度权重
- NAME_BOOST_THRESHOLD = 90：名称相似度 > 此值时加 30 分
- NAME_BOOST = 30：名称高相似度加分

加权规则（FROZEN 契约）：
- 类目层级权重：L3（规格集合，3 级）→ 1.0；L2（系列，2 级）→ 0.8；
  L1（大类，1 级）→ 0.5；
- 名称相似度 > 90 → 加 0.3（归一化到 0-100 即 +30，封顶 100）；
- L3 规格精确命中（query_spec == spec 且为 L3）→ 满置信 100.0。
"""
from rapidfuzz.fuzz import ratio, partial_ratio

# 阈值常量（单一事实源，所有调用方 import 此常量）
HIGH_CONF_SCORE = 90.0   # Top-1 分数门槛（原 98.0，2026-09-07 降至 90.0）
HIGH_CONF_GAP = 15.0     # Top-1 与 Top-2 分差门槛（原 10.0，2026-09-07 提至 15.0）
NAME_WEIGHT = 0.7        # 名称相似度权重
SPEC_WEIGHT = 0.3        # 规格相似度权重
NAME_BOOST_THRESHOLD = 90  # 名称相似度 > 此值时加分
NAME_BOOST = 30          # 名称高相似度加分（归一化到 0-100）


def _fuzz(a, b):
    """rapidfuzz 名称/规格相似度（取 ratio 与 partial_ratio 的较大值，0-100）。"""
    a = (a or '').strip()
    b = (b or '').strip()
    if not a or not b:
        return 0.0
    return max(ratio(a, b), partial_ratio(a, b))


def _category_level(cat_path):
    """类目层级深度（category_path 形如 'L1/L2/L3' → 3）。"""
    return len([p for p in (cat_path or '').split('/') if p and p.strip()])


def _category_weight(cat_path):
    """类目层级权重（L1=0.5 / L2=0.8 / L3=1.0）。"""
    return {3: 1.0, 2: 0.8, 1: 0.5}.get(_category_level(cat_path), 0.5)


def score_candidates(query_name, query_spec, dict_rows):
    """对候选字典行评分并按 score 降序返回。

    每个 dict_row 须含：id / name / spec / category_path（如 'L1/L2/L3'）。
    返回：[{dict_id, name, spec, score:float(0-100), category_path}, ...] 降序。
    """
    q_name = (query_name or '').strip()
    q_spec = (query_spec or '').strip()
    results = []
    for row in dict_rows or []:
        name = (row.get('name') or '').strip()
        spec = (row.get('spec') or '').strip()
        cat_path = row.get('category_path') or ''
        lvl = _category_level(cat_path)

        name_sim = _fuzz(q_name, name)
        spec_sim = _fuzz(q_spec, spec) if q_spec else 0.0

        # 基础分：名称主导、规格辅助
        base = NAME_WEIGHT * name_sim + SPEC_WEIGHT * spec_sim
        score = base * _category_weight(cat_path)

        # 名称相似度 > 阈值 加权（+NAME_BOOST，封顶 100）
        if name_sim > NAME_BOOST_THRESHOLD:
            score = min(100.0, score + NAME_BOOST)

        # L3 规格精确命中 → 满置信（M3 §5.6 高置信条件之一）
        if lvl == 3 and q_spec and spec and q_spec == spec:
            score = 100.0

        score = max(0.0, min(100.0, score))
        results.append({
            'dict_id': row.get('id'),
            'name': name,
            'spec': spec,
            'score': round(score, 2),
            'category_path': cat_path,
        })
    results.sort(key=lambda r: r['score'], reverse=True)
    return results


def high_confidence(candidates):
    """高置信判据（M3 §5.6）：Top-1 >= HIGH_CONF_SCORE 且 Top-1 与 Top-2 分差 > HIGH_CONF_GAP。

    无候选 → False；仅一个候选时以 0.0 作为 Top-2 基准。
    阈值常量：HIGH_CONF_SCORE=90.0, HIGH_CONF_GAP=15.0（2026-09-07 优化，原 98/10）。
    """
    if not candidates:
        return False
    top1 = candidates[0]['score']
    top2 = candidates[1]['score'] if len(candidates) > 1 else 0.0
    return top1 >= HIGH_CONF_SCORE and (top1 - top2) > HIGH_CONF_GAP
