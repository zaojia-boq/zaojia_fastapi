# -*- coding: utf-8 -*-
"""parse_gb_code / compute_match_key 纯函数测试（M1 §15 M1.2 验收判据）。

运行（AGENTS.md 登记 · 系统 Python，不依赖 odoo）：
    E:/Odoo19/venv/Scripts/python.exe -m pytest pure_tests/test_gb_code.py

覆盖：
- 编码解析 9/10/11/12/Z/未知 六类；
- 10 位异常映射 0302280006→030228006、0304130010→030413010；
- 同 9 位码 2013 与 2024 生成不同 match_key（F1）；
- Z 前缀生成 code:2024:Z<键>（F3）；
- 物料字典 / 标准化 / raw 兜底分支与版本维度。
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


gb_code = _load('gb_code')
parse_gb_code = gb_code.parse_gb_code
is_valid_gb_code = gb_code.is_valid_gb_code
compute_match_key = gb_code.compute_match_key
GB_CODE_10D_ANOMALIES = gb_code.GB_CODE_10D_ANOMALIES


# ----------------------------------------------------------------------
# parse_gb_code：编码解析六类
# ----------------------------------------------------------------------
class TestParseGbCode(unittest.TestCase):
    def test_12_to_9(self):
        # 12 位含自编顺序码 → 截前 9 位
        self.assertEqual(parse_gb_code('010101001001'), ('010101001', '010101001001'))

    def test_11_pad_to_12_then_9(self):
        # 11 位纯数字且首位≠0 → 补前导 0 成 12 位 → 截前 9 位
        self.assertEqual(parse_gb_code('10101001001'), ('010101001', '010101001001'))

    def test_9_unchanged(self):
        self.assertEqual(parse_gb_code('010101001'), ('010101001', '010101001'))

    def test_10_anomaly_mapped(self):
        # 已知异常 → 修正为 9 位（F2 裁决）
        self.assertEqual(parse_gb_code('0302280006'), ('030228006', '030228006'))
        self.assertEqual(parse_gb_code('0304130010'), ('030413010', '030413010'))

    def test_10_unknown_kept_with_warning(self):
        # 未知 10 位 → 原值入库，后续匹配退化为 raw
        code_9, code_full = parse_gb_code('1234567890')
        self.assertEqual(code_9, '1234567890')
        self.assertEqual(code_full, '1234567890')

    def test_z_prefix(self):
        # 2024 总图工程 Z 前缀 → 归一化 Z 键
        self.assertEqual(parse_gb_code('Z123'), ('Z123', 'Z123'))
        self.assertEqual(parse_gb_code('zAbC'), ('ZABC', 'ZABC'))

    def test_unknown_raw(self):
        # 含字母的自定义编码 → 原样返回
        self.assertEqual(parse_gb_code('ABC-001'), ('ABC-001', 'ABC-001'))

    def test_empty(self):
        self.assertEqual(parse_gb_code(''), ('', ''))
        self.assertEqual(parse_gb_code(None), ('', ''))

    def test_all_anomalies_mapped(self):
        # 设计稿 §4.7② 列出的全部异常映射都生效
        for bad, good in GB_CODE_10D_ANOMALIES.items():
            self.assertEqual(parse_gb_code(bad)[0], good)


# ----------------------------------------------------------------------
# is_valid_gb_code
# ----------------------------------------------------------------------
class TestIsValidGbCode:
    def test_valid(self):
        assert is_valid_gb_code('010101001')
    def test_invalid_len(self):
        assert not is_valid_gb_code('01010100')
        assert not is_valid_gb_code('0101010010')
    def test_invalid_non_digit(self):
        assert not is_valid_gb_code('Z123')
        assert not is_valid_gb_code('')


# ----------------------------------------------------------------------
# compute_match_key：版本维度 + 分支优先级（M1 §4.7② F1/F3）
# ----------------------------------------------------------------------
class TestComputeMatchKey(unittest.TestCase):
    def test_version_dimension_2013_vs_2024(self):
        # 同 9 位码、不同版本 → 不同 match_key（防跨版本误聚合）
        k13 = compute_match_key(item_code='010101001', item_code_version='2013')[0]
        k24 = compute_match_key(item_code='010101001', item_code_version='2024')[0]
        self.assertEqual(k13, 'code:2013:010101001|')
        self.assertEqual(k24, 'code:2024:010101001|')
        self.assertNotEqual(k13, k24)

    def test_no_version_unknown(self):
        self.assertEqual(
            compute_match_key(item_code='010101001')[0],
            'code:unknown:010101001|')

    def test_z_prefix_forces_2024(self):
        # Z 前缀 → code:2024:Z<键>（强制 version，忽略传入 version）
        self.assertEqual(
            compute_match_key(item_code='Z123', item_code_version='2013')[0],
            'code:2024:Z123|')

    def test_dict_priority(self):
        # 物料字典最高优先级，键型 = dict:<id>
        mk, src = compute_match_key(item_code='010101001', material_dict_id=42)
        self.assertEqual(mk, 'dict:42|')
        self.assertEqual(src, 'dict')

    def test_std_priority(self):
        mk, src = compute_match_key(item_name='电缆', std_name='电力电缆', std_spec='YJV')
        self.assertEqual(mk, 'std:电力电缆|YJV|')
        self.assertEqual(src, 'std')

    def test_raw_fallback_with_version(self):
        # 无编码无标准化 → raw 兜底，且带版本维度
        mk, src = compute_match_key(item_name='某清单项', item_code_version='2024')
        self.assertTrue(mk.startswith('raw:2024:'))
        self.assertEqual(src, 'raw')

    def test_unit_std_in_key(self):
        # unit_std 进入聚合键，跨工程聚合前置条件
        self.assertEqual(
            compute_match_key(item_code='010101001', unit_std='m', item_code_version='2024')[0],
            'code:2024:010101001|m')

    def test_anomaly_10_unknown_degrades_to_raw(self):
        # 未知 10 位 → 匹配失败 → raw 兜底（带原编码特征）
        mk, src = compute_match_key(item_code='1234567890')
        self.assertEqual(src, 'raw')
        self.assertTrue(mk.startswith('raw:'))
