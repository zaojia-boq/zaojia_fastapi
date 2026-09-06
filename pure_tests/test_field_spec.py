# -*- coding: utf-8 -*-
"""field_spec.py 字段分层定义 纯函数测试（数据安全根基）。

运行（系统 Python，不依赖 odoo）：
    python.exe -m pytest pure_tests/test_field_spec.py

覆盖：A/B/C 分层常量、B_DEFAULTS、DATA_SOURCE_TYPES、PRICE_STAT_TYPES、
is_b_field/is_a_field/classify_field/split_fields_by_layer 辅助函数。
这是数据安全的根基——B 类禁静默覆盖，必须有独立测试锁死。
"""
import os
import importlib.util
import unittest

# 按文件加载 data 模块，避免触发包 import
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, '..', 'data'))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_DATA, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


field_spec = _load('field_spec')


class TestFieldSpecConstants(unittest.TestCase):
    """A/B/C 分层常量完整性测试。"""

    def test_a_fields_count(self):
        """A 类（可重建）字段数量 = 21。"""
        self.assertEqual(len(field_spec.A_FIELDS), 21)

    def test_a_fields_contains_key_fields(self):
        """A 类包含核心可重建字段。"""
        for f in ('item_code', 'item_name', 'quantity', 'unit_rate', 'total',
                  'unit', 'unit_std', 'item_feature', 'source_path', 'source_sheet'):
            self.assertIn(f, field_spec.A_FIELDS, f"A_FIELDS 缺少 {f}")

    def test_b_fields_count(self):
        """B 类（不可重建）字段数量 = 6。"""
        self.assertEqual(len(field_spec.B_FIELDS), 6)

    def test_b_fields_exact(self):
        """B 类字段精确匹配（与 Odoo 版 boq_item.py:31 / upsert_service.py:36 一致）。"""
        expected = {'std_name', 'std_spec', 'material_dict_id',
                    'anomaly_flag', 'anomaly_reason', 'data_source_type'}
        self.assertEqual(field_spec.B_FIELDS, expected)

    def test_c_fields_count(self):
        """C 类（系统元数据）字段数量 = 10。"""
        self.assertEqual(len(field_spec.C_FIELDS), 10)

    def test_c_fields_contains_key_fields(self):
        """C 类包含核心系统字段。"""
        for f in ('id', 'biz_id', 'create_date', 'write_date', 'active',
                  'match_key', 'match_key_source', 'aggregate_id'):
            self.assertIn(f, field_spec.C_FIELDS, f"C_FIELDS 缺少 {f}")

    def test_abc_disjoint(self):
        """A/B/C 三类互不相交（import 时已 assert，测试再验证）。"""
        self.assertTrue(field_spec.A_FIELDS.isdisjoint(field_spec.B_FIELDS))
        self.assertTrue(field_spec.A_FIELDS.isdisjoint(field_spec.C_FIELDS))
        self.assertTrue(field_spec.B_FIELDS.isdisjoint(field_spec.C_FIELDS))

    def test_b_defaults(self):
        """B_DEFAULTS 包含 anomaly_flag=normal 和 data_source_type=completed。"""
        self.assertEqual(field_spec.B_DEFAULTS['anomaly_flag'], 'normal')
        self.assertEqual(field_spec.B_DEFAULTS['data_source_type'], 'completed')
        self.assertEqual(len(field_spec.B_DEFAULTS), 2)

    def test_data_source_types(self):
        """DATA_SOURCE_TYPES 包含 5 种数据性质。"""
        expected = {'completed', 'control_price', 'bid_price', 'pending_review', 'info_price'}
        self.assertEqual(field_spec.DATA_SOURCE_TYPES, expected)

    def test_price_stat_types_only_completed(self):
        """PRICE_STAT_TYPES 只包含 completed（历史均价默认只用已完工程）。"""
        self.assertEqual(field_spec.PRICE_STAT_TYPES, {'completed'})


class TestFieldSpecHelpers(unittest.TestCase):
    """分层辅助函数测试。"""

    def test_is_b_field_true(self):
        """is_b_field 对 B 类字段返回 True。"""
        for f in field_spec.B_FIELDS:
            self.assertTrue(field_spec.is_b_field(f), f"is_b_field({f}) 应为 True")

    def test_is_b_field_false(self):
        """is_b_field 对非 B 类字段返回 False。"""
        for f in ('item_code', 'quantity', 'active', 'unknown_field'):
            self.assertFalse(field_spec.is_b_field(f))

    def test_is_a_field_true(self):
        """is_a_field 对 A 类字段返回 True。"""
        for f in ('item_code', 'quantity', 'unit_rate'):
            self.assertTrue(field_spec.is_a_field(f))

    def test_is_a_field_false(self):
        """is_a_field 对非 A 类字段返回 False。"""
        for f in ('std_name', 'active', 'unknown'):
            self.assertFalse(field_spec.is_a_field(f))

    def test_classify_field_a(self):
        """classify_field 对 A 类返回 'A'。"""
        self.assertEqual(field_spec.classify_field('item_code'), 'A')
        self.assertEqual(field_spec.classify_field('quantity'), 'A')

    def test_classify_field_b(self):
        """classify_field 对 B 类返回 'B'。"""
        self.assertEqual(field_spec.classify_field('std_name'), 'B')
        self.assertEqual(field_spec.classify_field('data_source_type'), 'B')

    def test_classify_field_c(self):
        """classify_field 对 C 类返回 'C'。"""
        self.assertEqual(field_spec.classify_field('biz_id'), 'C')
        self.assertEqual(field_spec.classify_field('active'), 'C')

    def test_classify_field_unknown(self):
        """classify_field 对未知字段返回 'unknown'。"""
        self.assertEqual(field_spec.classify_field('nonexistent_field'), 'unknown')

    def test_split_fields_by_layer(self):
        """split_fields_by_layer 正确分层混合字段列表。"""
        result = field_spec.split_fields_by_layer(
            ['item_code', 'std_name', 'active', 'unknown_field', 'quantity', 'data_source_type']
        )
        self.assertEqual(set(result['A']), {'item_code', 'quantity'})
        self.assertEqual(set(result['B']), {'std_name', 'data_source_type'})
        self.assertEqual(set(result['C']), {'active'})
        self.assertEqual(set(result['unknown']), {'unknown_field'})

    def test_split_fields_by_layer_empty(self):
        """split_fields_by_layer 空列表返回空分层。"""
        result = field_spec.split_fields_by_layer([])
        self.assertEqual(result, {'A': [], 'B': [], 'C': [], 'unknown': []})

    def test_b_fields_not_in_a(self):
        """关键安全断言：所有 B 类字段都不在 A 类中（防静默覆盖）。"""
        for f in field_spec.B_FIELDS:
            self.assertNotIn(f, field_spec.A_FIELDS,
                             f"B 类字段 {f} 不应在 A 类中（否则会被静默覆盖）")


if __name__ == '__main__':
    unittest.main()
