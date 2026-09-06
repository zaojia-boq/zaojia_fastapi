# -*- coding: utf-8 -*-
"""match_score 纯函数测试（M3 §5.3 / §5.5 / §5.6 验收）。

运行（系统 Python，不依赖 odoo）：
    C:/Users/ht835/AppData/Local/Programs/Python/Python312/python.exe \
        -m pytest pure_tests/test_match_score.py -v

按 data 模块 importlib 加载模式（与 test_gb_code.py 一致）：直接按文件加载
match_score.py，避免触发 zaojia_boq 包（其 __init__ 会 import odoo）。
覆盖：
- 评分返回降序列表；
- high_confidence 逻辑（Top-1>=98 且 gap>10 → True；否则 False）；
- 精确名称命中排第一。
"""
import os
import importlib.util
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, '..', 'data'))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_DATA, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


match_score = _load('match_score')
score_candidates = match_score.score_candidates
high_confidence = match_score.high_confidence


# ----------------------------------------------------------------------
# 评分返回降序列表
# ----------------------------------------------------------------------
class TestScoreCandidatesOrdered(unittest.TestCase):
    def _rows(self):
        return [
            {'id': 1, 'name': '电力电缆', 'spec': 'YJV-3*150',
             'category_path': '电气/电缆/YJV-3*150'},
            {'id': 2, 'name': '控制电缆', 'spec': 'KVV-4*2.5',
             'category_path': '电气/电缆/KVV-4*2.5'},
            {'id': 3, 'name': '焊接钢管', 'spec': 'SC20',
             'category_path': '电气/导管/SC20'},
        ]

    def test_returns_sorted_desc(self):
        cands = score_candidates('电力电缆', 'YJV-3*150', self._rows())
        self.assertEqual(len(cands), 3)
        scores = [c['score'] for c in cands]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_top_is_exact_match(self):
        cands = score_candidates('电力电缆', 'YJV-3*150', self._rows())
        self.assertEqual(cands[0]['dict_id'], 1)
        self.assertGreaterEqual(cands[0]['score'], 98.0)

    def test_empty_query_no_crash(self):
        cands = score_candidates('', '', self._rows())
        self.assertEqual(len(cands), 3)
        # 空查询 → 所有相似度 0 → score 0（仍返回、可排序）
        self.assertTrue(all(c['score'] == 0.0 for c in cands))


# ----------------------------------------------------------------------
# high_confidence 逻辑
# ----------------------------------------------------------------------
class TestHighConfidence(unittest.TestCase):
    def test_true_when_top_high_and_gap_wide(self):
        cands = [
            {'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 100.0,
             'category_path': '电气/电缆/YJV'},
            {'dict_id': 2, 'name': '别的', 'spec': 'x', 'score': 60.0,
             'category_path': '电气/电缆/x'},
        ]
        self.assertTrue(high_confidence(cands))

    def test_false_when_top_below_98(self):
        cands = [
            {'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 85.0,
             'category_path': '电气/电缆/YJV'},
            {'dict_id': 2, 'name': '别的', 'spec': 'x', 'score': 40.0,
             'category_path': '电气/电缆/x'},
        ]
        self.assertFalse(high_confidence(cands))

    def test_false_when_gap_too_small(self):
        cands = [
            {'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 99.0,
             'category_path': '电气/电缆/YJV'},
            {'dict_id': 2, 'name': '电力电缆', 'spec': 'YJV2', 'score': 95.0,
             'category_path': '电气/电缆/YJV2'},
        ]
        self.assertFalse(high_confidence(cands))

    def test_true_when_top_exactly_98(self):
        # 边界：Top-1 恰 98.0（>=98 含等号）且分差 >10 → True
        cands = [
            {'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 98.0,
             'category_path': '电气/电缆/YJV'},
            {'dict_id': 2, 'name': '别的', 'spec': 'x', 'score': 50.0,
             'category_path': '电气/电缆/x'},
        ]
        self.assertTrue(high_confidence(cands))

    def test_false_when_gap_exactly_10(self):
        # 边界：分差恰 10.0（规则要求严格 >10，不含等号）→ False
        cands = [
            {'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 100.0,
             'category_path': '电气/电缆/YJV'},
            {'dict_id': 2, 'name': '电力电缆', 'spec': 'YJV2', 'score': 90.0,
             'category_path': '电气/电缆/YJV2'},
        ]
        self.assertFalse(high_confidence(cands))

    def test_false_when_empty(self):
        self.assertFalse(high_confidence([]))

    def test_true_single_candidate(self):
        cands = [
            {'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 100.0,
             'category_path': '电气/电缆/YJV'},
        ]
        self.assertTrue(high_confidence(cands))


# ----------------------------------------------------------------------
# 精确名称命中排第一（合成字典集）
# ----------------------------------------------------------------------
class TestExactNameRanksFirst(unittest.TestCase):
    def test_exact_name_top(self):
        rows = [
            {'id': 1, 'name': '聚氯乙烯绝缘电缆', 'spec': 'VV',
             'category_path': '电气/电缆/VV'},
            {'id': 2, 'name': '电力电缆', 'spec': 'YJV',
             'category_path': '电气/电缆/YJV'},
            {'id': 3, 'name': '交联聚乙烯电缆', 'spec': 'YJV22',
             'category_path': '电气/电缆/YJV22'},
        ]
        cands = score_candidates('电力电缆', 'YJV', rows)
        self.assertEqual(cands[0]['dict_id'], 2)


# ----------------------------------------------------------------------
# 加权规则 / 边界（M3 §5.3 / §5.5 / §5.6 契约强化）
# ----------------------------------------------------------------------
class TestScoreWeighting(unittest.TestCase):
    def _rows(self):
        return [
            {'id': 1, 'name': '镀锌钢管 DN100', 'spec': 'DN100',
             'category_path': '管材/钢管/镀锌钢管 DN100'},   # L3
            {'id': 2, 'name': '镀锌钢管 DN100', 'spec': 'DN100',
             'category_path': '管材/钢管'},                  # L2
            {'id': 3, 'name': '镀锌钢管 DN100', 'spec': 'DN100',
             'category_path': '管材'},                       # L1
        ]

    def test_l3_exact_spec_hit_is_full_confidence(self):
        cands = score_candidates('镀锌钢管 DN100', 'DN100', self._rows())
        top = cands[0]
        self.assertEqual(top['dict_id'], 1)
        self.assertEqual(top['score'], 100.0)

    def test_category_level_weight_orders_same_name(self):
        # 同名同规格下，层级越高权重越大 → L3 排最前
        cands = score_candidates('镀锌钢管 DN100', 'DN100', self._rows())
        ids = [c['dict_id'] for c in cands]
        self.assertEqual(ids, [1, 2, 3])

    def test_name_similarity_boost_above_90(self):
        rows = [
            {'id': 1, 'name': '电力电缆 YJV', 'spec': 'YJV',
             'category_path': '电气/电缆/YJV'},
            {'id': 2, 'name': '完全不同名', 'spec': 'x',
             'category_path': '电气/电缆/x'},
        ]
        cands = score_candidates('电力电缆 YJV', 'YJV', rows)
        self.assertGreater(cands[0]['score'], 90.0)


if __name__ == '__main__':
    unittest.main()
