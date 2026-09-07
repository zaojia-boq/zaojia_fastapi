# -*- coding: utf-8 -*-
"""FAISS 匹配器 + 学习引擎纯函数测试。"""
import os
import tempfile
import unittest

from data.faiss_matcher import FaissMatcher, match_with_faiss, fuse_three_algorithms, FAISS_AVAILABLE
from data.learning_engine import LearningEngine, DEFAULT_WEIGHTS, LEARNING_RATE


class TestFaissMatcher(unittest.TestCase):
    def setUp(self):
        self.dict_rows = [
            {'id': 1, 'name': '电力电缆', 'spec': 'YJV', 'category_path': '电气/电缆/YJV'},
            {'id': 2, 'name': '控制电缆', 'spec': 'KVV', 'category_path': '电气/电缆/KVV'},
            {'id': 3, 'name': '聚氯乙烯绝缘电缆', 'spec': 'VV', 'category_path': '电气/电缆/VV'},
            {'id': 4, 'name': '镀锌钢管', 'spec': 'DN50', 'category_path': '给排水/钢管/DN50'},
            {'id': 5, 'name': '焊接钢管', 'spec': 'DN100', 'category_path': '给排水/钢管/DN100'},
        ]
        self.matcher = FaissMatcher(self.dict_rows)

    @unittest.skipUnless(FAISS_AVAILABLE, "FAISS not available")
    def test_match_exact_name(self):
        cands = self.matcher.match('电力电缆', 'YJV', top_n=3)
        self.assertTrue(len(cands) > 0)
        # 电力电缆应该排第一
        self.assertEqual(cands[0]['dict_id'], 1)

    @unittest.skipUnless(FAISS_AVAILABLE, "FAISS not available")
    def test_match_similar_category(self):
        cands = self.matcher.match('交联聚乙烯电缆', 'YJV22', top_n=3)
        self.assertTrue(len(cands) > 0)
        # 应该匹配到电缆类，而不是钢管
        cat_paths = [c['category_path'] for c in cands]
        self.assertTrue(any('电缆' in p for p in cat_paths))

    @unittest.skipUnless(FAISS_AVAILABLE, "FAISS not available")
    def test_match_different_category(self):
        cands = self.matcher.match('镀锌钢管', 'DN50', top_n=3)
        self.assertTrue(len(cands) > 0)
        # 镀锌钢管应该排第一
        self.assertEqual(cands[0]['dict_id'], 4)

    @unittest.skipUnless(FAISS_AVAILABLE, "FAISS not available")
    def test_empty_query(self):
        cands = self.matcher.match('', '', top_n=5)
        self.assertEqual(cands, [])

    @unittest.skipUnless(FAISS_AVAILABLE, "FAISS not available")
    def test_empty_dict(self):
        matcher = FaissMatcher([])
        cands = matcher.match('电力电缆', 'YJV')
        self.assertEqual(cands, [])

    @unittest.skipUnless(FAISS_AVAILABLE, "FAISS not available")
    def test_score_range(self):
        cands = self.matcher.match('电力电缆', 'YJV', top_n=5)
        for c in cands:
            self.assertGreater(c['score'], 0)
            self.assertLessEqual(c['score'], 100)


class TestFuseThreeAlgorithms(unittest.TestCase):
    def test_fuse_all_three(self):
        rf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 95.0, 'category_path': '电气/电缆'}]
        tf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 80.0, 'category_path': '电气/电缆'}]
        faiss = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 85.0, 'category_path': '电气/电缆'}]
        fused = fuse_three_algorithms(rf, tf, faiss, rf_weight=0.3, tf_weight=0.35, faiss_weight=0.35)
        self.assertEqual(len(fused), 1)
        # 加权平均：0.3*95 + 0.35*80 + 0.35*85 = 28.5 + 28 + 29.75 = 86.25
        self.assertAlmostEqual(fused[0]['score'], 86.25, places=1)

    def test_fuse_only_two(self):
        rf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 95.0, 'category_path': '电气/电缆'}]
        tf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 80.0, 'category_path': '电气/电缆'}]
        faiss = []
        fused = fuse_three_algorithms(rf, tf, faiss)
        self.assertEqual(len(fused), 1)
        # 只有 rf 和 tf 有结果，按它们的权重归一化
        self.assertGreater(fused[0]['score'], 0)

    def test_fuse_different_ids(self):
        rf = [{'dict_id': 1, 'name': '电力电缆', 'spec': 'YJV', 'score': 95.0, 'category_path': '电气/电缆'}]
        tf = [{'dict_id': 2, 'name': '控制电缆', 'spec': 'KVV', 'score': 80.0, 'category_path': '电气/电缆'}]
        faiss = [{'dict_id': 3, 'name': '聚氯乙烯电缆', 'spec': 'VV', 'score': 70.0, 'category_path': '电气/电缆'}]
        fused = fuse_three_algorithms(rf, tf, faiss)
        self.assertEqual(len(fused), 3)
        # 按分数降序
        self.assertEqual(fused[0]['dict_id'], 1)


class TestLearningEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'learning_config.json')
        self.engine = LearningEngine(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_default_weights(self):
        weights = self.engine.get_weights()
        self.assertAlmostEqual(weights['rf'], DEFAULT_WEIGHTS['rf'], places=2)
        self.assertAlmostEqual(weights['tf'], DEFAULT_WEIGHTS['tf'], places=2)
        self.assertAlmostEqual(weights['faiss'], DEFAULT_WEIGHTS['faiss'], places=2)

    def test_record_confirmation_rf_hit(self):
        # rapidfuzz 命中，TF-IDF 和 FAISS 未命中
        result = self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1, rf_top1_score=95.0,
            tf_top1_dict_id=2, tf_top1_score=80.0,
            faiss_top1_dict_id=3, faiss_top1_score=70.0,
        )
        self.assertTrue(result['rf_hit'])
        self.assertFalse(result['tf_hit'])
        self.assertFalse(result['faiss_hit'])
        self.assertEqual(result['confirmation_count'], 1)
        # rf 权重应该增加
        self.assertGreater(result['weights']['rf'], DEFAULT_WEIGHTS['rf'])

    def test_record_confirmation_all_hit(self):
        # 三个算法都命中
        result = self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1, rf_top1_score=95.0,
            tf_top1_dict_id=1, tf_top1_score=80.0,
            faiss_top1_dict_id=1, faiss_top1_score=85.0,
        )
        self.assertTrue(result['rf_hit'])
        self.assertTrue(result['tf_hit'])
        self.assertTrue(result['faiss_hit'])
        # 三个权重都应该增加（但归一化后可能变化不大）
        self.assertAlmostEqual(sum(result['weights'].values()), 1.0, places=2)

    def test_weights_normalized(self):
        # 多次确认后，权重总和应该为 1
        for i in range(10):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1 if i % 2 == 0 else 2,
                tf_top1_dict_id=1 if i % 3 == 0 else 2,
                faiss_top1_dict_id=1 if i % 4 == 0 else 2,
            )
        weights = self.engine.get_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=2)

    def test_weights_within_range(self):
        # 权重应该在 [MIN_WEIGHT, MAX_WEIGHT] 范围内
        for i in range(100):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,  # 总是 rf 命中
                tf_top1_dict_id=2,
                faiss_top1_dict_id=2,
            )
        weights = self.engine.get_weights()
        for algo in ['rf', 'tf', 'faiss']:
            self.assertGreaterEqual(weights[algo], 0.1)
            self.assertLessEqual(weights[algo], 0.8)

    def test_persistence(self):
        # 确认后保存配置，重新加载应该恢复
        self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=2,
            faiss_top1_dict_id=3,
        )
        # 重新加载
        engine2 = LearningEngine(self.config_path)
        self.assertEqual(engine2.confirmation_count, 1)
        self.assertEqual(engine2.algorithm_hits['rf'], 1)

    def test_get_stats(self):
        self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=2,
            faiss_top1_dict_id=3,
        )
        stats = self.engine.get_stats()
        self.assertEqual(stats['confirmation_count'], 1)
        self.assertEqual(stats['algorithm_hits']['rf'], 1)
        self.assertEqual(stats['algorithm_hits']['tf'], 0)
        self.assertIn('hit_rates', stats)

    def test_reset(self):
        self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=2,
            faiss_top1_dict_id=3,
        )
        self.engine.reset()
        self.assertEqual(self.engine.confirmation_count, 0)
        self.assertAlmostEqual(self.engine.weights['rf'], DEFAULT_WEIGHTS['rf'], places=2)


if __name__ == '__main__':
    unittest.main()
