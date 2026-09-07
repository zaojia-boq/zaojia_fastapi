# -*- coding: utf-8 -*-
"""学习引擎 v2 纯函数测试。"""
import os
import tempfile
import unittest

from data.learning_engine_v2 import (
    LearningEngineV2, DEFAULT_WEIGHTS, BASE_LEARNING_RATE,
    PHASE1_THRESHOLD, PHASE2_THRESHOLD,
)


class TestLearningEngineV2Basic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'learning_v2.json')
        self.engine = LearningEngineV2(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_default_weights(self):
        weights = self.engine.get_weights()
        self.assertAlmostEqual(weights['rf'], DEFAULT_WEIGHTS['rf'], places=2)
        self.assertAlmostEqual(weights['tf'], DEFAULT_WEIGHTS['tf'], places=2)
        self.assertAlmostEqual(weights['faiss'], DEFAULT_WEIGHTS['faiss'], places=2)

    def test_weights_normalized(self):
        weights = self.engine.get_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=2)

    def test_record_confirmation_basic(self):
        result = self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1, rf_top1_score=95.0,
            tf_top1_dict_id=2, tf_top1_score=80.0,
            faiss_top1_dict_id=1, faiss_top1_score=85.0,
        )
        self.assertEqual(result['confirmation_count'], 1)
        self.assertTrue(result['rf_hit'])
        self.assertFalse(result['tf_hit'])
        self.assertTrue(result['faiss_hit'])
        self.assertIn('weights', result)
        self.assertIn('info_quality', result)
        self.assertIn('adaptive_lr', result)

    def test_record_confirmation_with_category(self):
        result = self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=1,
            faiss_top1_dict_id=1,
            category_path='电气/电缆/YJV',
        )
        self.assertEqual(result['category_prefix'], '电气/电缆')
        self.assertIn('category_weights', result)

        # 按类别获取权重
        cat_weights = self.engine.get_weights('电气/电缆/YJV')
        self.assertIn('rf', cat_weights)

    def test_record_confirmation_with_candidates(self):
        rf_cands = [
            {'dict_id': 2, 'name': '控制电缆', 'score': 90.0},
            {'dict_id': 1, 'name': '电力电缆', 'score': 85.0},
        ]
        tf_cands = [
            {'dict_id': 1, 'name': '电力电缆', 'score': 85.0},
            {'dict_id': 2, 'name': '控制电缆', 'score': 80.0},
        ]
        faiss_cands = [
            {'dict_id': 1, 'name': '电力电缆', 'score': 80.0},
            {'dict_id': 2, 'name': '控制电缆', 'score': 75.0},
        ]
        result = self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=2, rf_top1_score=90.0,
            tf_top1_dict_id=1, tf_top1_score=85.0,
            faiss_top1_dict_id=1, faiss_top1_score=80.0,
            rf_candidates=rf_cands,
            tf_candidates=tf_cands,
            faiss_candidates=faiss_cands,
        )
        # rf 的确认候选排名是 1（Top-2）
        self.assertEqual(result['rf_rank'], 1)
        self.assertEqual(result['tf_rank'], 0)
        self.assertEqual(result['faiss_rank'], 0)


class TestAdaptiveLearningRate(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV2()

    def test_phase1_higher_lr(self):
        # 初期（确认数 < 100）学习率更高
        lr1 = self.engine._get_adaptive_learning_rate(0.5)
        # 模拟 600 次确认后
        self.engine.confirmation_count = 600
        lr3 = self.engine._get_adaptive_learning_rate(0.5)
        self.assertGreater(lr1, lr3)

    def test_high_info_higher_lr(self):
        # 高信息量确认学习率更高
        lr_low = self.engine._get_adaptive_learning_rate(0.2)
        lr_high = self.engine._get_adaptive_learning_rate(0.9)
        self.assertGreater(lr_high, lr_low)

    def test_lr_within_bounds(self):
        for info in [0.0, 0.5, 1.0]:
            lr = self.engine._get_adaptive_learning_rate(info)
            self.assertGreaterEqual(lr, 0.02)
            self.assertLessEqual(lr, 0.25)


class TestInfoQuality(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV2()

    def test_high_disagreement_high_info(self):
        # 各算法 Top-1 完全不一致 → 高信息量
        info = self.engine._calculate_info_quality(
            rf_top1_dict_id=1, tf_top1_dict_id=2, faiss_top1_dict_id=3,
            rf_top1_score=90, tf_top1_score=85, faiss_top1_score=80,
        )
        self.assertGreater(info, 0.5)

    def test_full_agreement_low_info(self):
        # 各算法 Top-1 完全一致 → 低信息量
        info = self.engine._calculate_info_quality(
            rf_top1_dict_id=1, tf_top1_dict_id=1, faiss_top1_dict_id=1,
            rf_top1_score=95, tf_top1_score=90, faiss_top1_score=92,
        )
        self.assertLess(info, 0.5)

    def test_info_within_bounds(self):
        info = self.engine._calculate_info_quality(1, 2, 3, 90, 85, 80)
        self.assertGreaterEqual(info, 0.0)
        self.assertLessEqual(info, 1.0)


class TestUncertaintyScore(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV2()

    def test_high_uncertainty_disagreement(self):
        # 各算法 Top-1 不一致 + 低分 + 小分差 → 高不确定性
        result = self.engine.get_uncertainty_score(
            rf_top1_dict_id=1, tf_top1_dict_id=2, faiss_top1_dict_id=3,
            rf_top1_score=70, tf_top1_score=68, faiss_top1_score=65,
            rf_top2_score=69, tf_top2_score=67, faiss_top2_score=64,
        )
        self.assertEqual(result['level'], 'high')
        self.assertGreater(result['score'], 0.6)

    def test_low_uncertainty_agreement(self):
        # 各算法 Top-1 一致 + 高分 + 大分差 → 低不确定性
        result = self.engine.get_uncertainty_score(
            rf_top1_dict_id=1, tf_top1_dict_id=1, faiss_top1_dict_id=1,
            rf_top1_score=95, tf_top1_score=92, faiss_top1_score=90,
            rf_top2_score=70, tf_top2_score=65, faiss_top2_score=60,
        )
        self.assertEqual(result['level'], 'low')
        self.assertLess(result['score'], 0.3)

    def test_uncertainty_reasons(self):
        result = self.engine.get_uncertainty_score(
            rf_top1_dict_id=1, tf_top1_dict_id=2, faiss_top1_dict_id=3,
            rf_top1_score=70, tf_top1_score=68, faiss_top1_score=65,
        )
        self.assertIsInstance(result['reasons'], list)
        self.assertGreater(len(result['reasons']), 0)


class TestRejectionLearning(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'learning_v2.json')
        self.engine = LearningEngineV2(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_record_rejection(self):
        result = self.engine.record_rejection(
            query_name='电力电缆',
            query_spec='YJV',
            rejected_dict_id=2,
            rejected_by_algorithm='rf',
        )
        self.assertEqual(result['rejection_count'], 1)
        self.assertEqual(result['algorithm_misses']['rf'], 1)

    def test_rejection_decreases_weight(self):
        # 先记录一些确认让权重稳定
        for i in range(10):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,
                tf_top1_dict_id=1,
                faiss_top1_dict_id=1,
            )
        rf_weight_before = self.engine.get_weights()['rf']

        # 记录 rf 的拒绝
        self.engine.record_rejection(
            query_name='测试',
            query_spec='spec',
            rejected_dict_id=2,
            rejected_by_algorithm='rf',
        )
        rf_weight_after = self.engine.get_weights()['rf']
        self.assertLess(rf_weight_after, rf_weight_before)


class TestCategoryLearning(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'learning_v2.json')
        self.engine = LearningEngineV2(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_different_categories_different_weights(self):
        # 电气类别：rf 总是命中
        for i in range(20):
            self.engine.record_confirmation(
                query_name=f'电气{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,
                tf_top1_dict_id=2,
                faiss_top1_dict_id=2,
                category_path='电气/电缆/YJV',
            )

        # 给排水类别：tf 总是命中
        for i in range(20):
            self.engine.record_confirmation(
                query_name=f'给排水{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=2,
                tf_top1_dict_id=1,
                faiss_top1_dict_id=2,
                category_path='给排水/钢管/DN50',
            )

        elec_weights = self.engine.get_weights('电气/电缆/YJV')
        water_weights = self.engine.get_weights('给排水/钢管/DN50')

        # 电气类别的 rf 权重应该高于给排水类别
        self.assertGreater(elec_weights['rf'], water_weights['rf'])
        # 给排水类别的 tf 权重应该高于电气类别
        self.assertGreater(water_weights['tf'], elec_weights['tf'])


class TestPersistence(unittest.TestCase):
    def test_save_and_load(self):
        temp_dir = tempfile.mkdtemp()
        config_path = os.path.join(temp_dir, 'learning_v2.json')

        engine1 = LearningEngineV2(config_path)
        engine1.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=1,
            faiss_top1_dict_id=1,
            category_path='电气/电缆/YJV',
        )

        # 重新加载
        engine2 = LearningEngineV2(config_path)
        self.assertEqual(engine2.confirmation_count, 1)
        self.assertEqual(engine2.algorithm_hits['rf'], 1)
        self.assertIn('电气/电缆', engine2.category_weights)

        # 清理
        os.remove(config_path)
        os.rmdir(temp_dir)


class TestStats(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV2()

    def test_get_stats(self):
        self.engine.record_confirmation(
            query_name='测试',
            query_spec='spec',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=1,
            faiss_top1_dict_id=1,
        )
        stats = self.engine.get_stats()
        self.assertEqual(stats['confirmation_count'], 1)
        self.assertIn('hit_rates', stats)
        self.assertIn('global_weights', stats)
        self.assertIn('category_count', stats)


class TestReset(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'learning_v2.json')
        self.engine = LearningEngineV2(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_reset_all(self):
        self.engine.record_confirmation(
            query_name='测试',
            query_spec='spec',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=1,
            faiss_top1_dict_id=1,
        )
        self.engine.reset()
        self.assertEqual(self.engine.confirmation_count, 0)
        self.assertAlmostEqual(self.engine.weights['rf'], DEFAULT_WEIGHTS['rf'], places=2)

    def test_reset_category(self):
        self.engine.record_confirmation(
            query_name='测试',
            query_spec='spec',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=1,
            faiss_top1_dict_id=1,
            category_path='电气/电缆/YJV',
        )
        self.engine.reset(category='电气/电缆/YJV')
        self.assertNotIn('电气/电缆', self.engine.category_weights)
        # 全局权重不受影响
        self.assertEqual(self.engine.confirmation_count, 1)


if __name__ == '__main__':
    unittest.main()
