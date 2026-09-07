# -*- coding: utf-8 -*-
"""TF-IDF 匹配器纯函数测试。"""
import unittest

from data.tfidf_matcher import TfidfMatcher, match_with_tfidf, fuse_scores, _tokenize


class TestTokenize(unittest.TestCase):
    def test_chinese_tokenize(self):
        words = _tokenize('电力电缆YJV')
        self.assertTrue(len(words) > 0)
        # jieba 可能分成"电力电缆"或"电力"+"电缆"，只要包含电缆相关词即可
        self.assertTrue(any('电缆' in w for w in words))
        self.assertIn('YJV', words)

    def test_empty(self):
        self.assertEqual(_tokenize(''), [])
        self.assertEqual(_tokenize(None), [])

    def test_stop_words_filtered(self):
        words = _tokenize('的电缆')
        self.assertNotIn('的', words)
        self.assertIn('电缆', words)


class TestTfidfMatcher(unittest.TestCase):
    def setUp(self):
        self.dict_rows = [
            {'id': 1, 'name': '电力电缆', 'spec': 'YJV', 'category_path': '电气/电缆/YJV'},
            {'id': 2, 'name': '控制电缆', 'spec': 'KVV', 'category_path': '电气/电缆/KVV'},
            {'id': 3, 'name': '聚氯乙烯绝缘电缆', 'spec': 'VV', 'category_path': '电气/电缆/VV'},
            {'id': 4, 'name': '镀锌钢管', 'spec': 'DN50', 'category_path': '给排水/钢管/DN50'},
            {'id': 5, 'name': '焊接钢管', 'spec': 'DN100', 'category_path': '给排水/钢管/DN100'},
        ]
        self.matcher = TfidfMatcher(self.dict_rows)

    def test_match_exact_name(self):
        cands = self.matcher.match('电力电缆', 'YJV', top_n=3)
        self.assertTrue(len(cands) > 0)
        # 电力电缆应该排第一
        self.assertEqual(cands[0]['dict_id'], 1)

    def test_match_similar_name(self):
        cands = self.matcher.match('交联聚乙烯电缆', 'YJV22', top_n=3)
        self.assertTrue(len(cands) > 0)
        # 应该匹配到电缆类，而不是钢管
        cat_paths = [c['category_path'] for c in cands]
        self.assertTrue(any('电缆' in p for p in cat_paths))

    def test_match_different_category(self):
        cands = self.matcher.match('镀锌钢管', 'DN50', top_n=3)
        self.assertTrue(len(cands) > 0)
        # 镀锌钢管应该排第一
        self.assertEqual(cands[0]['dict_id'], 4)

    def test_empty_query(self):
        cands = self.matcher.match('', '', top_n=5)
        self.assertEqual(cands, [])

    def test_empty_dict(self):
        matcher = TfidfMatcher([])
        cands = matcher.match('电力电缆', 'YJV')
        self.assertEqual(cands, [])

    def test_score_range(self):
        cands = self.matcher.match('电力电缆', 'YJV', top_n=5)
        for c in cands:
            self.assertGreater(c['score'], 0)
            self.assertLessEqual(c['score'], 100)


class TestMatchWithTfidf(unittest.TestCase):
    def test_convenience_function(self):
        dict_rows = [
            {'id': 1, 'name': '电力电缆', 'spec': 'YJV', 'category_path': '电气/电缆'},
        ]
        cands = match_with_tfidf('电力电缆', 'YJV', dict_rows, top_n=1)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]['dict_id'], 1)


class TestFuseScores(unittest.TestCase):
    def test_fuse_both_sources(self):
        rf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 95.0, 'category_path': '电气/电缆'}]
        tf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 80.0, 'category_path': '电气/电缆'}]
        fused = fuse_scores(rf, tf, rapidfuzz_weight=0.5, tfidf_weight=0.5)
        self.assertEqual(len(fused), 1)
        # 加权平均：0.5*95 + 0.5*80 = 87.5
        self.assertAlmostEqual(fused[0]['score'], 87.5, places=1)

    def test_fuse_only_rapidfuzz(self):
        rf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 95.0, 'category_path': '电气/电缆'}]
        tf = []
        fused = fuse_scores(rf, tf)
        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]['score'], 95.0)

    def test_fuse_different_ids(self):
        rf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 95.0, 'category_path': '电气/电缆'}]
        tf = [{'dict_id': 2, 'name': '控制电缆', 'spec': 'KVV', 'score': 80.0, 'category_path': '电气/电缆'}]
        fused = fuse_scores(rf, tf)
        self.assertEqual(len(fused), 2)
        # 按分数降序
        self.assertEqual(fused[0]['dict_id'], 1)
        self.assertEqual(fused[1]['dict_id'], 2)


if __name__ == '__main__':
    unittest.main()
