# -*- coding: utf-8 -*-
"""quality_metrics 纯函数测试（M3 §3.2 / §7.1 验收判据）。

运行（AGENTS.md 登记 · 系统 Python，不依赖 odoo）：
    C:/Users/ht835/AppData/Local/Programs/Python/Python312/python.exe -m pytest pure_tests/test_quality_metrics.py -v

覆盖：
- coverage 计算（3/4 → 0.75）
- match_key_quality（dict+std 占比）
- anomaly_rate（error 占比）
- m3_pass / m4_pass 阈值（coverage 0.75 & anomaly 0.10 → m3_pass True, m4_pass False）
- data_source_dist 分布
- 空行 / default_deviation_threshold() == 30

纯函数测试：直接按文件加载 data 模块，避免触发 zaojia_boq 包（其 __init__ 会 import odoo）。
"""
import os
import importlib.util
import unittest

# 纯函数测试：直接按文件加载 data 模块，避免触发 zaojia_boq 包（其 __init__ 会 import odoo）。
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, '..', 'data'))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_DATA, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


quality_metrics = _load('quality_metrics')
compute_metrics = quality_metrics.compute_metrics
default_deviation_threshold = quality_metrics.default_deviation_threshold


def _rows(n_total, n_covered, n_error, n_high_quality_src=None):
    """构造 n_total 行；前 n_covered 行带 material_dict_id；前 n_error 行 anomaly='error'。

    n_high_quality_src：额外让前 N 行 match_key_source 设为 'dict'/'std'（其余 'raw'）。
    """
    n_high_quality_src = n_high_quality_src if n_high_quality_src is not None else n_covered
    rows = []
    for i in range(n_total):
        src = 'dict' if i < n_high_quality_src else 'raw'
        rows.append({
            'material_dict_id': (i + 1) if i < n_covered else False,
            'match_key_source': src,
            'data_source_type': 'completed' if i % 2 == 0 else 'pending_review',
            'anomaly_flag': 'error' if i < n_error else 'normal',
        })
    return rows


class TestComputeMetrics(unittest.TestCase):

    # ------------------------------------------------------------------
    # coverage
    # ------------------------------------------------------------------
    def test_coverage_3_of_4(self):
        # 3/4 行带 material_dict_id → 0.75
        m = compute_metrics(_rows(4, n_covered=3, n_error=0))
        self.assertAlmostEqual(m['coverage'], 0.75, places=6)

    def test_coverage_empty(self):
        m = compute_metrics(_rows(4, n_covered=0, n_error=0))
        self.assertAlmostEqual(m['coverage'], 0.0, places=6)

    # ------------------------------------------------------------------
    # match_key_quality
    # ------------------------------------------------------------------
    def test_match_key_quality_dict_std(self):
        # 前 2 行 source='dict'（高优），其余 'raw' → 2/4 = 0.5
        m = compute_metrics(_rows(4, n_covered=4, n_error=0, n_high_quality_src=2))
        self.assertAlmostEqual(m['match_key_quality'], 0.5, places=6)

    def test_match_key_quality_all_high(self):
        m = compute_metrics(_rows(4, n_covered=4, n_error=0, n_high_quality_src=4))
        self.assertAlmostEqual(m['match_key_quality'], 1.0, places=6)

    # ------------------------------------------------------------------
    # anomaly_rate
    # ------------------------------------------------------------------
    def test_anomaly_rate(self):
        # 2/4 error → 0.5
        m = compute_metrics(_rows(4, n_covered=4, n_error=2))
        self.assertAlmostEqual(m['anomaly_rate'], 0.5, places=6)

    # ------------------------------------------------------------------
    # m3_pass / m4_pass 阈值（§7.1）
    # ------------------------------------------------------------------
    def test_m3_pass_true_m4_pass_false(self):
        # coverage 0.75 & anomaly 0.10 → m3 达标(>=0.70 & <0.15)，m4 不达标(coverage<0.80)
        m = compute_metrics(_rows(20, n_covered=15, n_error=2))
        self.assertAlmostEqual(m['coverage'], 0.75, places=6)
        self.assertAlmostEqual(m['anomaly_rate'], 0.10, places=6)
        self.assertTrue(m['m3_pass'], 'M3 门应达标')
        self.assertFalse(m['m4_pass'], 'M4 门应不达标（coverage<0.80）')

    def test_m4_pass_true(self):
        # coverage 0.85 & anomaly 0.05 → 双达标
        m = compute_metrics(_rows(20, n_covered=17, n_error=1))
        self.assertAlmostEqual(m['coverage'], 0.85, places=6)
        self.assertAlmostEqual(m['anomaly_rate'], 0.05, places=6)
        self.assertTrue(m['m3_pass'])
        self.assertTrue(m['m4_pass'], 'M4 门应达标')

    def test_m3_pass_false_high_anomaly(self):
        # coverage 0.80 & anomaly 0.20 → m3 不达标（anomaly>=0.15）
        m = compute_metrics(_rows(20, n_covered=16, n_error=4))
        self.assertAlmostEqual(m['coverage'], 0.80, places=6)
        self.assertAlmostEqual(m['anomaly_rate'], 0.20, places=6)
        self.assertFalse(m['m3_pass'])
        self.assertFalse(m['m4_pass'])

    def test_m3_boundary_coverage_exactly_070(self):
        # 门槛边界：coverage 恰 0.70（规则 >=0.70 含等号）& anomaly 0.10 → m3 达标
        m = compute_metrics(_rows(20, n_covered=14, n_error=2))
        self.assertAlmostEqual(m['coverage'], 0.70, places=6)
        self.assertAlmostEqual(m['anomaly_rate'], 0.10, places=6)
        self.assertTrue(m['m3_pass'], 'coverage 恰 0.70 应达标（>=）')
        self.assertFalse(m['m4_pass'], 'coverage<0.80，M4 不达标')

    def test_m3_boundary_anomaly_exactly_015(self):
        # 门槛边界：anomaly 恰 0.15（规则严格 <0.15 不含等号）→ m3 不达标
        m = compute_metrics(_rows(20, n_covered=18, n_error=3))
        self.assertAlmostEqual(m['coverage'], 0.90, places=6)
        self.assertAlmostEqual(m['anomaly_rate'], 0.15, places=6)
        self.assertFalse(m['m3_pass'], 'anomaly 恰 0.15 应不达标（严格 <0.15）')
        self.assertFalse(m['m4_pass'], 'anomaly 0.15>=0.10，M4 亦不达标')

    def test_m4_boundary_coverage_exactly_080(self):
        # 门槛边界：coverage 恰 0.80（规则 >=0.80 含等号）& anomaly 0.05 → m4 达标
        m = compute_metrics(_rows(20, n_covered=16, n_error=1))
        self.assertAlmostEqual(m['coverage'], 0.80, places=6)
        self.assertAlmostEqual(m['anomaly_rate'], 0.05, places=6)
        self.assertTrue(m['m3_pass'])
        self.assertTrue(m['m4_pass'], 'coverage 恰 0.80 应达标（>=）')

    def test_m4_boundary_anomaly_exactly_010(self):
        # 门槛边界：anomaly 恰 0.10（规则严格 <0.10 不含等号）→ m4 不达标；m3 达标
        m = compute_metrics(_rows(20, n_covered=18, n_error=2))
        self.assertAlmostEqual(m['coverage'], 0.90, places=6)
        self.assertAlmostEqual(m['anomaly_rate'], 0.10, places=6)
        self.assertTrue(m['m3_pass'], 'anomaly 0.10<0.15，M3 达标')
        self.assertFalse(m['m4_pass'], 'anomaly 恰 0.10 应不达标（严格 <0.10）')

    # ------------------------------------------------------------------
    # data_source_dist
    # ------------------------------------------------------------------
    def test_data_source_dist(self):
        rows = [
            {'material_dict_id': 1, 'match_key_source': 'dict', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': 2, 'match_key_source': 'std', 'data_source_type': 'completed', 'anomaly_flag': 'normal'},
            {'material_dict_id': False, 'match_key_source': 'raw', 'data_source_type': 'pending_review', 'anomaly_flag': 'normal'},
            {'material_dict_id': False, 'match_key_source': 'code', 'data_source_type': 'pending_review', 'anomaly_flag': 'error'},
        ]
        m = compute_metrics(rows)
        self.assertEqual(m['data_source_dist'].get('completed'), 2)
        self.assertEqual(m['data_source_dist'].get('pending_review'), 2)
        self.assertEqual(sum(m['data_source_dist'].values()), 4)

    # ------------------------------------------------------------------
    # 空行 / 默认值
    # ------------------------------------------------------------------
    def test_empty_rows(self):
        m = compute_metrics([])
        self.assertEqual(m['coverage'], 0.0)
        self.assertEqual(m['match_key_quality'], 0.0)
        self.assertEqual(m['anomaly_rate'], 0.0)
        self.assertFalse(m['m3_pass'])
        self.assertFalse(m['m4_pass'])
        self.assertEqual(m['data_source_dist'], {})

    def test_default_deviation_threshold(self):
        self.assertEqual(default_deviation_threshold(), 30)


if __name__ == '__main__':
    unittest.main()
