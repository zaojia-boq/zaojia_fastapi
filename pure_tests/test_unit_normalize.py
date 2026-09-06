# -*- coding: utf-8 -*-
"""unit_normalize.py 单位归一化 纯函数测试（M1 §4.7③）。

运行（系统 Python，不依赖 odoo）：
    python.exe -m pytest pure_tests/test_unit_normalize.py
"""
import os
import importlib.util
import unittest

# 按文件加载 data 模块，避免触发 zaojia_boq 包 import odoo
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, '..', 'data'))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_DATA, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


unit_normalize = _load('unit_normalize')
normalize_unit = unit_normalize.normalize_unit


class TestUnitNormalize(unittest.TestCase):
    def test_length_meter_variants(self):
        # 米 / m / M / 米(m) / 延米 / 延长米 → m
        for v in ('米', 'm', 'M', '米(m)', '延米', '延长米'):
            self.assertEqual(normalize_unit(v), ('m', False))

    def test_mass_variants(self):
        for v in ('千克', 'kg', 'KG', '公斤'):
            self.assertEqual(normalize_unit(v), ('kg', False))

    def test_ton_variants(self):
        for v in ('吨', 't', 'T'):
            self.assertEqual(normalize_unit(v), ('t', False))

    def test_area_variants(self):
        for v in ('平方米', '平米', 'm2', 'm²'):
            self.assertEqual(normalize_unit(v), ('㎡', False))

    def test_volume_variants(self):
        for v in ('立方米', '立方', 'm3', 'm³'):
            self.assertEqual(normalize_unit(v), ('m³', False))

    def test_count_variants(self):
        # 计数类同义与全半角变体
        for v in ('台', '套', '个', '组', '块', '根', '处'):
            std, warn = normalize_unit(v)
            self.assertEqual(warn, False)
            self.assertEqual(std, v)

    def test_fullwidth_space_normalized(self):
        # 全角空格 / 内部空格不干扰
        self.assertEqual(normalize_unit('　米　'), ('m', False))

    def test_unknown_marks_warning(self):
        # 未命中 → 原样小写 + warning；原始 unit 不被覆盖（由调用方保留）
        std, warn = normalize_unit('根/台')
        self.assertEqual(warn, True)
        self.assertEqual(std, '根/台')

    def test_empty(self):
        self.assertEqual(normalize_unit(''), ('', False))
        self.assertEqual(normalize_unit(None), ('', False))


if __name__ == '__main__':
    unittest.main()
