# -*- coding: utf-8 -*-
"""price_calc 纯函数测试（M3 §9.1 验收判据）。

运行（系统 Python，不依赖 odoo）：
    C:/Users/ht835/AppData/Local/Programs/Python/Python312/python.exe -m pytest pure_tests/test_price_calc.py -v

覆盖（M3模块设计.md §3 / §9.1）：
- 偏离百分比 deviation_pct(130,100)==30.0；零均值安全返回 0.0；
- 区间判定 prices=[100,110,120,200] 阈值 30% → 200 判为异常；
- 样本下限 sample_count=2 < 3 → 不判异常；
- compute_kpis：domain-like 行的样本数/均价/区间/异常数；
- compute_kpis：过滤 None；
- analyze_group：按 province / match_key_source 分组聚合。
"""
import os
import importlib.util
try:
    import pytest
except ImportError:
    pytest = None
import unittest

# 纯函数测试：直接按文件加载 data 模块，避免触发 zaojia_boq 包（其 __init__ 会 import odoo）。
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, '..', 'data'))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_DATA, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


price_calc = _load('price_calc')
deviation_pct = price_calc.deviation_pct
is_anomaly = price_calc.is_anomaly
compute_kpis = price_calc.compute_kpis
analyze_group = price_calc.analyze_group


# ----------------------------------------------------------------------
# deviation_pct
# ----------------------------------------------------------------------
class TestDeviationPct(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(deviation_pct(130, 100), 30.0)

    def test_negative(self):
        self.assertEqual(deviation_pct(80, 100), -20.0)

    def test_zero_avg_safe(self):
        # historical_avg == 0 → 0.0（避免除零）
        self.assertEqual(deviation_pct(50, 0), 0.0)


# ----------------------------------------------------------------------
# is_anomaly（区间判定 + 样本下限）
# ----------------------------------------------------------------------
class TestIsAnomaly(unittest.TestCase):
    def test_interval_200_is_anomaly(self):
        # prices=[100,110,120,200]，avg=132.5，阈值 30%
        # 200 偏离 (200-132.5)/132.5=50.9% > 30% → 异常
        self.assertTrue(is_anomaly(200, 132.5, threshold=0.30, sample_count=4))

    def test_interval_120_not_anomaly(self):
        # 120 偏离 (120-132.5)/132.5=-9.4% → 正常
        self.assertFalse(is_anomaly(120, 132.5, threshold=0.30, sample_count=4))

    def test_sample_floor_blocks_anomaly(self):
        # 样本数 2 < 3 → 即便偏离很大也不判异常（M3 §3.4 样本下限）
        big_dev = abs(deviation_pct(200, 132.5)) > 30.0
        self.assertTrue(big_dev)  # 确认偏离确实超阈值
        self.assertFalse(is_anomaly(200, 132.5, threshold=0.30, sample_count=2))

    def test_exact_threshold_not_anomaly(self):
        # 偏离恰好 30% → 不超（严格 > ）
        self.assertFalse(is_anomaly(130, 100, threshold=0.30, sample_count=3))


# ----------------------------------------------------------------------
# compute_kpis
# ----------------------------------------------------------------------
class TestComputeKpis(unittest.TestCase):
    def test_domain_like_rows(self):
        rows = [
            {'unit_rate_num': 100.0},
            {'unit_rate_num': 110.0},
            {'unit_rate_num': 120.0},
            {'unit_rate_num': 200.0},
        ]
        k = compute_kpis(rows)
        self.assertEqual(k['sample_count'], 4)
        self.assertAlmostEqual(k['avg'], 132.5, places=6)
        self.assertEqual(k['min'], 100.0)
        self.assertEqual(k['max'], 200.0)
        # 仅 200 偏离均值 >30% → anomaly_count=1
        self.assertEqual(k['anomaly_count'], 1)

    def test_filters_none(self):
        rows = [
            {'unit_rate_num': 100.0},
            {'unit_rate_num': None},
            {'unit_rate_num': 120.0},
            {'unit_rate_num': None},
        ]
        k = compute_kpis(rows)
        self.assertEqual(k['sample_count'], 2)
        self.assertAlmostEqual(k['avg'], 110.0, places=6)
        self.assertEqual(k['anomaly_count'], 0)

    def test_empty(self):
        k = compute_kpis([])
        self.assertEqual(k['sample_count'], 0)
        self.assertEqual(k['avg'], 0.0)
        self.assertEqual(k['anomaly_count'], 0)


# ----------------------------------------------------------------------
# analyze_group
# ----------------------------------------------------------------------
class TestAnalyzeGroup(unittest.TestCase):
    def test_group_by_province(self):
        rows = [
            {'unit_rate_num': 100.0, 'province': '广东'},
            {'unit_rate_num': 110.0, 'province': '广东'},
            {'unit_rate_num': 200.0, 'province': '北京'},
        ]
        out = analyze_group(rows, 'province')
        by = {g['group']: g for g in out}
        self.assertIn('广东', by)
        self.assertIn('北京', by)
        self.assertEqual(by['广东']['count'], 2)
        self.assertAlmostEqual(by['广东']['avg'], 105.0, places=6)
        self.assertEqual(by['北京']['count'], 1)
        self.assertEqual(by['北京']['max'], 200.0)

    def test_invalid_group_key(self):
        with self.assertRaises(ValueError):
            analyze_group([{'unit_rate_num': 1.0}], 'not_a_dim')

    def test_group_with_none_skipped(self):
        rows = [
            {'unit_rate_num': None, 'match_key_source': 'code'},
            {'unit_rate_num': 50.0, 'match_key_source': 'code'},
        ]
        out = analyze_group(rows, 'match_key_source')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['count'], 1)
        self.assertEqual(out[0]['min'], 50.0)


class TestAnalyzeGroupExtra(unittest.TestCase):
    def test_group_by_aggregate_id(self):
        # M3 §3.3 核心维度：aggregate_id 跨行聚合身份
        rows = [
            {'unit_rate_num': 90.0, 'aggregate_id': 'dict:5'},
            {'unit_rate_num': 110.0, 'aggregate_id': 'dict:5'},
            {'unit_rate_num': 200.0, 'aggregate_id': 'code:030801001'},
        ]
        out = analyze_group(rows, 'aggregate_id')
        by = {g['group']: g for g in out}
        self.assertEqual(by['dict:5']['count'], 2)
        self.assertAlmostEqual(by['dict:5']['avg'], 100.0, places=6)
        self.assertEqual(by['code:030801001']['count'], 1)
        self.assertEqual(by['code:030801001']['max'], 200.0)

    def test_group_by_price_period_string(self):
        # price_period 由服务转 str（如 "2026-08-01"）后分组
        rows = [
            {'unit_rate_num': 80.0, 'price_period': '2026-08-01'},
            {'unit_rate_num': 82.0, 'price_period': '2026-08-01'},
            {'unit_rate_num': 90.0, 'price_period': '2026-09-01'},
        ]
        out = analyze_group(rows, 'price_period')
        by = {g['group']: g for g in out}
        self.assertEqual(by['2026-08-01']['count'], 2)
        self.assertEqual(by['2026-09-01']['count'], 1)

    def test_group_with_none_group_key(self):
        # 无分组值的行应单独成组（group=None），不混入其他组
        rows = [
            {'unit_rate_num': 10.0, 'province': None},
            {'unit_rate_num': 20.0, 'province': '广东'},
        ]
        out = analyze_group(rows, 'province')
        by = {g['group']: g for g in out}
        self.assertIn(None, by)
        self.assertEqual(by[None]['count'], 1)
        self.assertEqual(by['广东']['count'], 1)


class TestComputeKpisFloor(unittest.TestCase):
    def test_single_sample_no_anomaly(self):
        # 样本数 1 < 下限 3 → 不判异常（与 §3.4 样本下限一致）
        rows = [{'unit_rate_num': 999.0}]
        k = compute_kpis(rows)
        self.assertEqual(k['sample_count'], 1)
        self.assertEqual(k['anomaly_count'], 0)

    def test_anomaly_count_relative_to_batch(self):
        # compute_kpis 异常相对本批 avg 判定（阈值 0.30、下限 3）
        rows = [
            {'unit_rate_num': 100.0},
            {'unit_rate_num': 100.0},
            {'unit_rate_num': 100.0},
            {'unit_rate_num': 200.0},  # 偏离 100% > 30%，样本 4≥3 → 异常
        ]
        k = compute_kpis(rows)
        self.assertEqual(k['anomaly_count'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
