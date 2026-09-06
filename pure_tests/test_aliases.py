# -*- coding: utf-8 -*-
"""aliases.py 表头别名映射 纯函数测试（M1 §7）。

运行（系统 Python，不依赖 odoo）：
    python.exe -m pytest pure_tests/test_aliases.py

v1.1 更新：map_headers 返回3元组（增加 multi_hit），新增 extract_field_value
首个非空列回退测试。
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


aliases = _load('aliases')
normalize_header = aliases.normalize_header
map_header = aliases.map_header
map_headers = aliases.map_headers
extract_field_value = aliases.extract_field_value
validate_required = aliases.validate_required


class TestAliases(unittest.TestCase):
    def test_normalize_strips_and_lowers(self):
        # 去空白 + 全角→半角 + 大写转小写
        self.assertEqual(normalize_header('  综 合 单 价（元） '), '综合单价(元)')
        self.assertEqual(normalize_header('Item_Code'), 'item_code')

    def test_map_header_direct(self):
        self.assertEqual(map_header('项目编码'), 'item_code')
        self.assertEqual(map_header('编码'), 'item_code')
        self.assertEqual(map_header('项目名称'), 'item_name')
        self.assertEqual(map_header('NAME'), 'item_name')

    def test_map_header_unknown(self):
        self.assertIsNone(map_header('完全不相关的列'))

    def test_map_headers_multivalue_first_wins(self):
        # 多列命中同一规范字段 → header_map 取首个，其余不进 unrecognized，全部记录在 multi_hit
        header_map, unrecognized, multi_hit = map_headers(['项目名称', '名称', '综合单价'])
        self.assertEqual(header_map, {0: 'item_name', 2: 'unit_rate'})
        self.assertEqual(unrecognized, [])  # 多列命中的其余列不再进 unrecognized
        self.assertEqual(multi_hit, {'item_name': [0, 1], 'unit_rate': [2]})

    def test_map_headers_unrecognized_to_extra(self):
        # 未识别列进 unrecognized，不报错
        header_map, unrecognized, multi_hit = map_headers(['工程名称', '神秘列', '数量'])
        self.assertEqual(header_map, {0: 'project_name', 2: 'quantity'})
        self.assertEqual(unrecognized, [(1, '神秘列')])
        self.assertEqual(multi_hit, {'project_name': [0], 'quantity': [2]})

    def test_map_headers_multi_hit_three_columns(self):
        # 三列命中同一字段，multi_hit 记录全部三列
        header_map, unrecognized, multi_hit = map_headers(['单价', '综合单价', '清单单价', '数量'])
        self.assertEqual(header_map, {0: 'unit_rate', 3: 'quantity'})
        self.assertEqual(unrecognized, [])
        self.assertEqual(multi_hit['unit_rate'], [0, 1, 2])
        self.assertEqual(multi_hit['quantity'], [3])

    def test_validate_required_missing(self):
        # 缺 item_name → 返回缺失列表（调用方应整表终止）
        header_map, _, _ = map_headers(['工程名称', '综合单价'])
        self.assertEqual(validate_required(header_map), ['item_name'])

    def test_validate_required_ok(self):
        header_map, _, _ = map_headers(['项目名称'])
        self.assertEqual(validate_required(header_map), [])

    def test_fullwidth_and_space_variants(self):
        # 全角括号、内部空格变体都能命中
        self.assertEqual(map_header('项 目 编 码'), 'item_code')
        self.assertEqual(map_header('清单单价'), 'unit_rate')


class TestExtractFieldValue(unittest.TestCase):
    """首个非空列回退测试（v1.1 修复：多列命中时首列为空不丢数据）。"""

    def test_first_column_has_value(self):
        # 第一列有值 → 取第一列
        self.assertEqual(extract_field_value(['电缆', '', None], [0, 1, 2]), '电缆')

    def test_first_empty_second_has_value(self):
        # 第一列为空、第二列有值 → 回退取第二列（核心修复点）
        self.assertEqual(extract_field_value(['', '电力电缆', None], [0, 1, 2]), '电力电缆')

    def test_first_two_empty_third_has_value(self):
        # 前两列为空、第三列有值 → 回退取第三列
        self.assertEqual(extract_field_value(['', None, 'YJV'], [0, 1, 2]), 'YJV')

    def test_all_empty_returns_none(self):
        # 全部为空 → 返回 None
        self.assertIsNone(extract_field_value(['', None, '  '], [0, 1, 2]))

    def test_whitespace_only_treated_as_empty(self):
        # 纯空白字符串视为空
        self.assertEqual(extract_field_value(['   ', '\t', '实际值'], [0, 1, 2]), '实际值')

    def test_index_out_of_range_skipped(self):
        # 列索引超出行长度 → 跳过不报错
        self.assertEqual(extract_field_value(['值'], [0, 5, 10]), '值')

    def test_numeric_zero_is_not_empty(self):
        # 数字 0 是有效值，不应被视为空
        self.assertEqual(extract_field_value([0, 1], [0, 1]), 0)

    def test_false_is_not_empty(self):
        # False 是有效值
        self.assertEqual(extract_field_value([False, True], [0, 1]), False)

    def test_integration_with_map_headers(self):
        # 集成测试：map_headers 识别多列命中 → extract_field_value 回退取非空值
        header_map, unrecognized, multi_hit = map_headers(['项目名称', '名称', '数量'])
        # 模拟数据行：第一列项目名称为空，第二列名称有值
        data_row = ['', '电缆敷设', 100]
        value = extract_field_value(data_row, multi_hit['item_name'])
        self.assertEqual(value, '电缆敷设')  # 首列为空，回退取第二列，不丢数据


if __name__ == '__main__':
    unittest.main()
