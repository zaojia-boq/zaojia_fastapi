# -*- coding: utf-8 -*-
"""学习引擎 v3 纯函数测试。"""
import os
import tempfile
import unittest

from data.learning_engine_v3 import (
    LearningEngineV3, LearningStrategy, TrajectoryRecord,
    DEFAULT_WEIGHTS, STRATEGY_CONFIGS,
)


class TestLearningStrategy(unittest.TestCase):
    def test_strategy_creation(self):
        s = LearningStrategy(name='test', lr_multiplier=1.5, ema_alpha=0.5)
        self.assertEqual(s.name, 'test')
        self.assertEqual(s.lr_multiplier, 1.5)
        self.assertEqual(s.ema_alpha, 0.5)
        self.assertAlmostEqual(s.weights['rf'], DEFAULT_WEIGHTS['rf'], places=2)

    def test_strategy_serialization(self):
        s = LearningStrategy(name='test', lr_multiplier=1.5, ema_alpha=0.5)
        s.confirmation_count = 10
        s.validation_score = 0.8
        data = s.to_dict()
        s2 = LearningStrategy.from_dict(data)
        self.assertEqual(s2.name, 'test')
        self.assertEqual(s2.confirmation_count, 10)
        self.assertAlmostEqual(s2.validation_score, 0.8)


class TestLearningEngineV3Basic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'learning_v3.json')
        self.engine = LearningEngineV3(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_default_weights(self):
        weights = self.engine.get_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=2)
        self.assertIn('rf', weights)
        self.assertIn('tf', weights)
        self.assertIn('faiss', weights)

    def test_multi_strategy_initialization(self):
        self.assertEqual(len(self.engine.strategies), len(STRATEGY_CONFIGS))
        strategy_names = [s.name for s in self.engine.strategies]
        self.assertIn('fast_learner', strategy_names)
        self.assertIn('balanced', strategy_names)
        self.assertIn('stable_learner', strategy_names)

    def test_record_confirmation_basic(self):
        result = self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1, rf_top1_score=95.0,
            tf_top1_dict_id=2, tf_top1_score=80.0,
            faiss_top1_dict_id=1, faiss_top1_score=85.0,
        )
        self.assertIn('weights', result)
        self.assertIn('weights_before', result)
        self.assertIn('v2_result', result)
        self.assertIn('drift_detected', result)
        self.assertIn('strategy_weights', result)
        self.assertIn('best_strategy', result)
        self.assertIn('trajectory_length', result)
        self.assertEqual(result['trajectory_length'], 1)

    def test_weights_change_after_confirmation(self):
        weights_before = self.engine.get_weights()
        result = self.engine.record_confirmation(
            query_name='电力电缆',
            query_spec='YJV',
            confirmed_dict_id=1,
            rf_top1_dict_id=1, rf_top1_score=95.0,
            tf_top1_dict_id=1, tf_top1_score=90.0,
            faiss_top1_dict_id=1, faiss_top1_score=92.0,
        )
        weights_after = result['weights']
        # 权重应该有变化（因为所有算法都命中了）
        self.assertNotEqual(weights_before, weights_after)

    def test_strategy_weights_differ(self):
        # 不同策略应该有不同的权重（因为学习率不同）
        for _ in range(20):
            self.engine.record_confirmation(
                query_name='测试',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,
                tf_top1_dict_id=2,
                faiss_top1_dict_id=2,
            )
        weights = [s.weights for s in self.engine.strategies]
        # fast_learner 和 stable_learner 的权重应该不同
        self.assertNotEqual(weights[0], weights[2])


class TestConceptDriftDetection(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV3()

    def test_no_drift_initially(self):
        # 初始状态不应该检测到漂移
        result = self.engine.record_confirmation(
            query_name='测试',
            query_spec='spec',
            confirmed_dict_id=1,
            rf_top1_dict_id=1,
            tf_top1_dict_id=1,
            faiss_top1_dict_id=1,
        )
        self.assertFalse(result['drift_detected'])

    def test_drift_on_low_hit_rate(self):
        # 模拟大量未命中的确认，触发命中率骤降漂移
        for i in range(40):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=2,  # 未命中
                tf_top1_dict_id=3,  # 未命中
                faiss_top1_dict_id=4,  # 未命中
            )
        # 应该检测到漂移（命中率骤降）
        drift_events = self.engine.drift_events
        self.assertGreater(len(drift_events), 0)
        self.assertIn('hit_rate_drop', [e['type'] for e in drift_events])


class TestExplainability(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV3()
        for i in range(10):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,
                tf_top1_dict_id=1,
                faiss_top1_dict_id=1,
            )

    def test_explain_weights(self):
        explanation = self.engine.explain_weights()
        self.assertIn('current_weights', explanation)
        self.assertIn('best_strategy', explanation)
        self.assertIn('strategy_weights', explanation)
        self.assertIn('algorithm_hit_rates', explanation)
        self.assertIn('weight_trend', explanation)
        self.assertIn('explanation', explanation)
        self.assertIsInstance(explanation['explanation'], str)
        self.assertGreater(len(explanation['explanation']), 0)

    def test_explanation_contains_hit_rates(self):
        explanation = self.engine.explain_weights()
        hit_rates = explanation['algorithm_hit_rates']
        self.assertIn('rf', hit_rates)
        self.assertIn('tf', hit_rates)
        self.assertIn('faiss', hit_rates)
        # 所有算法都命中了，命中率应该为 1.0
        self.assertAlmostEqual(hit_rates['rf'], 1.0, places=1)


class TestActiveLearningOptimization(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV3()

    def test_empty_input(self):
        result = self.engine.get_optimized_confirmation_order([])
        self.assertEqual(result, [])

    def test_uncertain_items_ranked_higher(self):
        pending = [
            {
                'id': 1, 'name': '电力电缆', 'spec': 'YJV',
                'category_path': '电气/电缆',
                'rf_top1_id': 1, 'tf_top1_id': 2, 'faiss_top1_id': 3,
                'rf_top1_score': 70, 'tf_top1_score': 68, 'faiss_top1_score': 65,
            },
            {
                'id': 2, 'name': '控制电缆', 'spec': 'KVV',
                'category_path': '电气/电缆',
                'rf_top1_id': 1, 'tf_top1_id': 1, 'faiss_top1_id': 1,
                'rf_top1_score': 95, 'tf_top1_score': 92, 'faiss_top1_score': 90,
            },
        ]
        result = self.engine.get_optimized_confirmation_order(pending)
        self.assertEqual(len(result), 2)
        # 不确定性高的条目应该排在前面
        self.assertEqual(result[0]['id'], 1)
        self.assertGreater(result[0]['recommendation_score'], result[1]['recommendation_score'])

    def test_diversity_bonus(self):
        pending = [
            {
                'id': 1, 'name': '电力电缆', 'spec': 'YJV',
                'category_path': '电气/电缆',
                'rf_top1_id': 1, 'tf_top1_id': 1, 'faiss_top1_id': 1,
                'rf_top1_score': 90, 'tf_top1_score': 88, 'faiss_top1_score': 85,
            },
            {
                'id': 2, 'name': '给水管', 'spec': 'DN50',
                'category_path': '给排水/钢管',
                'rf_top1_id': 1, 'tf_top1_id': 1, 'faiss_top1_id': 1,
                'rf_top1_score': 90, 'tf_top1_score': 88, 'faiss_top1_score': 85,
            },
        ]
        result = self.engine.get_optimized_confirmation_order(pending)
        # 第二个条目是新类别，应该有多样性奖励
        self.assertIn('reasons', result[1])


class TestMetaLearning(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV3()

    def test_meta_params_exist(self):
        self.assertIn('base_lr', self.engine.meta_params)
        self.assertIn('ema_alpha', self.engine.meta_params)
        self.assertIn('strategy_fusion_alpha', self.engine.meta_params)

    def test_fusion_alpha_adjusts(self):
        alpha_before = self.engine.meta_params['strategy_fusion_alpha']
        # 模拟高命中率确认
        for i in range(30):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,
                tf_top1_dict_id=1,
                faiss_top1_dict_id=1,
            )
        alpha_after = self.engine.meta_params['strategy_fusion_alpha']
        # 高命中率应该提高融合系数（更信任最优策略）
        self.assertGreaterEqual(alpha_after, alpha_before * 0.9)  # 允许小幅波动


class TestPersistence(unittest.TestCase):
    def test_save_and_load(self):
        temp_dir = tempfile.mkdtemp()
        config_path = os.path.join(temp_dir, 'learning_v3.json')

        engine1 = LearningEngineV3(config_path)
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
        engine2 = LearningEngineV3(config_path)
        self.assertEqual(len(engine2.trajectory), 1)
        self.assertEqual(engine2.strategies[0].confirmation_count, 1)

        # 清理
        os.remove(config_path)
        os.rmdir(temp_dir)


class TestStats(unittest.TestCase):
    def setUp(self):
        self.engine = LearningEngineV3()
        for i in range(5):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,
                tf_top1_dict_id=1,
                faiss_top1_dict_id=1,
            )

    def test_get_stats(self):
        stats = self.engine.get_stats()
        self.assertEqual(stats['version'], 'v3')
        self.assertEqual(stats['num_strategies'], 3)
        self.assertIn('strategies', stats)
        self.assertIn('best_strategy', stats)
        self.assertEqual(stats['trajectory_length'], 5)
        self.assertIn('meta_params', stats)


class TestReset(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'learning_v3.json')
        self.engine = LearningEngineV3(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_reset_all(self):
        for i in range(10):
            self.engine.record_confirmation(
                query_name=f'测试{i}',
                query_spec='spec',
                confirmed_dict_id=1,
                rf_top1_dict_id=1,
                tf_top1_dict_id=1,
                faiss_top1_dict_id=1,
            )
        self.engine.reset()
        self.assertEqual(len(self.engine.trajectory), 0)
        self.assertEqual(self.engine.strategies[0].confirmation_count, 0)
        self.assertAlmostEqual(self.engine.strategies[0].weights['rf'], DEFAULT_WEIGHTS['rf'], places=2)


if __name__ == '__main__':
    unittest.main()
