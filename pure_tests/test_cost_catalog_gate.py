# -*- coding: utf-8 -*-
"""cost_catalog_gate 纯函数测试（M3.6 / M4 启动判据验收）。

运行（AGENTS.md 登记 · 系统 Python，不依赖 odoo）：
    C:/Users/ht835/AppData/Local/Programs/Python/Python312/python.exe -m pytest pure_tests/test_cost_catalog_gate.py -v

覆盖：
- 双门槛判定（覆盖率 ≥80% 且 异常率 <10%）：通过 / 单项不通过 / 双项不通过；
- **边界语义**：覆盖率取 ≥（0.80 通过），异常率取 <（0.10 不通过）——卡在门槛上不放行；
- blockers 人类可读说明（供 UI 提示）；
- evaluate_gate_from_metrics 与 quality_metrics.compute_metrics 联动；
- **防漂移**：本模块 M4_* 常量必须与 quality_metrics.M4_* 相等（本地定义是
  为遵守 data/ 目录「互不交叉 import」惯例，故须由本测试守卫）。
- 空数据 / 全 0 不放行（空库不得启动成本库）。

纯函数测试：直接按文件加载 data 模块，避免触发 zaojia_boq 包（其 __init__ 会 import odoo）。
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


gate = _load('cost_catalog_gate')
quality_metrics = _load('quality_metrics')

evaluate_gate = gate.evaluate_gate
evaluate_gate_from_metrics = gate.evaluate_gate_from_metrics


class TestCostCatalogGate(unittest.TestCase):
    """M3.6 成本库启动门槛 —— 双门槛判定。"""

    # ------------------------------------------------------------------
    # 1. 通过
    # ------------------------------------------------------------------
    def test_pass_both_ok(self):
        """覆盖 0.90 / 异常 0.05 → 双门槛通过。"""
        r = evaluate_gate(0.90, 0.05)
        self.assertTrue(r['passed'])
        self.assertTrue(r['coverage_ok'])
        self.assertTrue(r['anomaly_ok'])
        self.assertEqual(r['blockers'], [])

    def test_pass_exact_coverage_boundary(self):
        """边界：覆盖率恰好 0.80 → ≥ 语义，通过。"""
        r = evaluate_gate(0.80, 0.0)
        self.assertTrue(r['coverage_ok'], '覆盖率取 ≥：0.80 应通过')
        self.assertTrue(r['passed'])

    def test_anomaly_exact_boundary_rejected(self):
        """边界：异常率恰好 0.10 → < 语义，**不通过**（卡在门槛上不放行）。"""
        r = evaluate_gate(1.0, 0.10)
        self.assertFalse(r['anomaly_ok'], '异常率取 <：0.10 不应通过')
        self.assertFalse(r['passed'])
        self.assertEqual(len(r['blockers']), 1)

    # ------------------------------------------------------------------
    # 2. 单项 / 双项不通过
    # ------------------------------------------------------------------
    def test_fail_low_coverage_only(self):
        """仅覆盖率不足 → passed=False，blockers 只有 1 条且点名覆盖率。"""
        r = evaluate_gate(0.50, 0.01)
        self.assertFalse(r['coverage_ok'])
        self.assertTrue(r['anomaly_ok'])
        self.assertFalse(r['passed'])
        self.assertEqual(len(r['blockers']), 1)
        self.assertIn('覆盖率', r['blockers'][0])

    def test_fail_high_anomaly_only(self):
        """仅异常率超限 → blockers 点名异常率。"""
        r = evaluate_gate(0.95, 0.40)
        self.assertTrue(r['coverage_ok'])
        self.assertFalse(r['anomaly_ok'])
        self.assertFalse(r['passed'])
        self.assertEqual(len(r['blockers']), 1)
        self.assertIn('异常率', r['blockers'][0])

    def test_fail_both(self):
        """双项不通过 → blockers 2 条。"""
        r = evaluate_gate(0.10, 0.90)
        self.assertFalse(r['passed'])
        self.assertEqual(len(r['blockers']), 2)

    # ------------------------------------------------------------------
    # 3. 空数据不得放行（防 GIGO：空库建成本库 = 垃圾进垃圾出）
    # ------------------------------------------------------------------
    def test_zeros_do_not_pass(self):
        """coverage=0 / anomaly=0 → 覆盖率不足，不通过。"""
        r = evaluate_gate(0.0, 0.0)
        self.assertFalse(r['passed'], '空数据不得视为达标')

    def test_none_treated_as_zero(self):
        """None 按 0 处理，不崩溃。"""
        r = evaluate_gate(None, None)
        self.assertFalse(r['passed'])
        self.assertEqual(r['coverage'], 0.0)
        self.assertEqual(r['anomaly_rate'], 0.0)

    # ------------------------------------------------------------------
    # 4. 自定义门槛（供未来调参 / 分阶段验收）
    # ------------------------------------------------------------------
    def test_custom_thresholds(self):
        """可传入自定义门槛（如 M3 阶段用 0.70 / 0.15）。"""
        r = evaluate_gate(0.75, 0.12, min_coverage=0.70, max_anomaly=0.15)
        self.assertTrue(r['passed'])
        self.assertEqual(r['thresholds'],
                         {'min_coverage': 0.70, 'max_anomaly': 0.15})

    # ------------------------------------------------------------------
    # 5. 与 quality_metrics 联动
    # ------------------------------------------------------------------
    def test_from_metrics_matches_m4_pass(self):
        """evaluate_gate_from_metrics().passed 必须与 compute_metrics().m4_pass 一致。

        两者判定逻辑必须等价，否则会出现「仪表盘显示 M4 达标，但成本库门槛拦着」
        或反之的矛盾。
        """
        cases = [
            # (rows, 期望一致)
            ([{'material_dict_id': 1, 'anomaly_flag': 'normal'}] * 9
             + [{'material_dict_id': False, 'anomaly_flag': 'normal'}], True),
            # 覆盖 0.9 / 异常 0.1 → 异常率不达标（<10% 严格）
            ([{'material_dict_id': 1, 'anomaly_flag': 'normal'}] * 9
             + [{'material_dict_id': 1, 'anomaly_flag': 'error'}], True),
            # 覆盖 0.5 → 双项均不达标
            ([{'material_dict_id': 1, 'anomaly_flag': 'normal'}]
             + [{'material_dict_id': False, 'anomaly_flag': 'normal'}], True),
        ]
        for rows, _ in cases:
            m = quality_metrics.compute_metrics(rows)
            r = evaluate_gate_from_metrics(m)
            self.assertEqual(r['passed'], m['m4_pass'],
                             '门槛判定与 m4_pass 不一致：coverage=%s anomaly=%s'
                             % (m['coverage'], m['anomaly_rate']))

    def test_from_metrics_empty(self):
        """空 metrics（无 key）→ 按 0 处理，不放行。"""
        self.assertFalse(evaluate_gate_from_metrics({})['passed'])
        self.assertFalse(evaluate_gate_from_metrics(None)['passed'])

    # ------------------------------------------------------------------
    # 6. 防漂移守卫（本地定义常量 vs quality_metrics 常量）
    # ------------------------------------------------------------------
    def test_thresholds_consistent_with_quality_metrics(self):
        """本模块 M4_* 必须与 quality_metrics.M4_* 相等。

        cost_catalog_gate 为遵守 data/ 目录「互不交叉 import」惯例而本地定义常量，
        故由本测试守卫两处不漂移 —— 否则仪表盘与成本库门槛会给出矛盾结论。
        """
        self.assertEqual(gate.M4_COVERAGE_MIN, quality_metrics.M4_COVERAGE_MIN,
                         '覆盖率门槛漂移：cost_catalog_gate 与 quality_metrics 不一致')
        self.assertEqual(gate.M4_ANOMALY_MAX, quality_metrics.M4_ANOMALY_MAX,
                         '异常率门槛漂移：cost_catalog_gate 与 quality_metrics 不一致')


if __name__ == '__main__':
    unittest.main()
