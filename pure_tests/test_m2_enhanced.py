# -*- coding: utf-8 -*-
"""M2 深化模块纯函数测试（多格式解析 + 字段映射 + 校验引擎 + 归档增强）。"""
import io
import os
import tempfile
import unittest

from data.file_parser import (
    detect_file_type, validate_file_type, parse_file,
    is_summary_row, list_sheets, MAGIC_NUMBERS,
)
from data.field_mapper import (
    auto_map_headers, validate_mapping, save_template, load_template,
    list_templates, find_best_template, apply_mapping_to_row, STANDARD_FIELDS,
)
from data.validation_engine import (
    validate_rows, get_rule_templates, create_rule,
    ValidationReport, LEVEL_ERROR, LEVEL_WARNING, BUILTIN_RULES,
)
from data.archive_enhanced import (
    calculate_file_hash, calculate_bytes_hash, compress_file, decompress_file,
    ArchiveMetadata, ArchiveIntegrityChecker, ArchiveSearch, ArchiveCleaner,
    COMPRESS_ZIP, COMPRESS_GZIP,
)


class TestFileParser(unittest.TestCase):
    def test_detect_xlsx(self):
        # xlsx 文件以 PK 开头（ZIP 格式）
        data = MAGIC_NUMBERS['xlsx/xlsm/zip'] + b'PK\x03\x04 test'
        self.assertEqual(detect_file_type(data, 'test.xlsx'), 'xlsx')

    def test_detect_xlsm(self):
        data = MAGIC_NUMBERS['xlsx/xlsm/zip'] + b'test'
        self.assertEqual(detect_file_type(data, 'test.xlsm'), 'xlsm')

    def test_detect_csv_with_bom(self):
        data = MAGIC_NUMBERS['csv_utf8_bom'] + b'name,value\n'
        self.assertEqual(detect_file_type(data, 'test.csv'), 'csv')

    def test_detect_unknown(self):
        data = b'not a valid file'
        self.assertEqual(detect_file_type(data, 'test.xyz'), 'unknown')

    def test_validate_unsupported(self):
        is_valid, file_type = validate_file_type(b'unknown', 'test.xyz')
        self.assertFalse(is_valid)
        self.assertEqual(file_type, 'unknown')

    def test_parse_csv(self):
        csv_data = '项目名称,项目特征,单位,工程量\n电力电缆,YJV,m,100\n控制电缆,KVV,m,50\n'.encode('utf-8')
        result = parse_file(csv_data, 'test.csv')
        self.assertEqual(result['file_type'], 'csv')
        self.assertEqual(result['row_count'], 2)
        self.assertIn('项目名称', result['headers'])

    def test_parse_csv_with_gbk(self):
        # GBK 编码的 CSV
        csv_data = '项目名称,工程量\n电力电缆,100\n'.encode('gbk')
        result = parse_file(csv_data, 'test.csv')
        self.assertEqual(result['row_count'], 1)

    def test_is_summary_row(self):
        self.assertTrue(is_summary_row(['合计', '100']))
        self.assertTrue(is_summary_row(['总计', '200']))
        self.assertTrue(is_summary_row(['小计', '50']))
        self.assertFalse(is_summary_row(['电力电缆', '100']))

    def test_list_sheets_csv(self):
        csv_data = 'name,value\ntest,1\n'.encode('utf-8')
        sheets = list_sheets(csv_data, 'test.csv')
        self.assertEqual(sheets, ['CSV'])


class TestFieldMapper(unittest.TestCase):
    def test_auto_map_headers(self):
        headers = ['项目名称', '项目特征', '单位', '工程量', '综合单价', '合价']
        mapping = auto_map_headers(headers)
        self.assertEqual(mapping.get('项目名称'), 'item_name')
        self.assertEqual(mapping.get('项目特征'), 'item_feature')
        self.assertEqual(mapping.get('单位'), 'unit')
        self.assertEqual(mapping.get('工程量'), 'quantity')

    def test_auto_map_aliases(self):
        headers = ['名称', '规格型号', '计量单位', '数量']
        mapping = auto_map_headers(headers)
        self.assertEqual(mapping.get('名称'), 'item_name')
        self.assertEqual(mapping.get('规格型号'), 'item_feature')
        self.assertEqual(mapping.get('计量单位'), 'unit')
        self.assertEqual(mapping.get('数量'), 'quantity')

    def test_validate_mapping_valid(self):
        mapping = {'项目名称': 'item_name', '工程量': 'quantity'}
        headers = ['项目名称', '工程量']
        result = validate_mapping(mapping, headers)
        self.assertTrue(result['valid'])

    def test_validate_mapping_unknown_field(self):
        mapping = {'项目名称': 'item_name', '未知列': 'unknown_field'}
        headers = ['项目名称', '未知列']
        result = validate_mapping(mapping, headers)
        self.assertFalse(result['valid'])
        self.assertIn('unknown_field', result['unknown_fields'])

    def test_validate_mapping_duplicate(self):
        mapping = {'列1': 'item_name', '列2': 'item_name'}
        headers = ['列1', '列2']
        result = validate_mapping(mapping, headers)
        self.assertFalse(result['valid'])

    def test_apply_mapping_to_row(self):
        headers = ['项目名称', '工程量']
        mapping = {'项目名称': 'item_name', '工程量': 'quantity'}
        row = ['电力电缆', 100]
        result = apply_mapping_to_row(row, headers, mapping)
        self.assertEqual(result['item_name'], '电力电缆')
        self.assertEqual(result['quantity'], 100)

    def test_template_save_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 临时修改模板目录
            import data.field_mapper as fm
            from pathlib import Path
            original_dir = fm.TEMPLATE_DIR
            fm.TEMPLATE_DIR = Path(tmpdir)

            try:
                mapping = {'项目名称': 'item_name'}
                headers = ['项目名称']
                result = save_template('测试模板', mapping, headers, description='测试')
                self.assertTrue(result['ok'])

                loaded = load_template('测试模板')
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded['name'], '测试模板')
                self.assertEqual(loaded['mapping'], mapping)
            finally:
                fm.TEMPLATE_DIR = original_dir

    def test_find_best_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import data.field_mapper as fm
            from pathlib import Path
            original_dir = fm.TEMPLATE_DIR
            fm.TEMPLATE_DIR = Path(tmpdir)

            try:
                # 保存一个模板
                save_template(
                    '标准造价模板',
                    {'项目名称': 'item_name', '工程量': 'quantity'},
                    ['项目名称', '项目特征', '单位', '工程量'],
                    filename_pattern=r'.*造价.*',
                )

                # 查找匹配模板
                tpl, score = find_best_template(
                    ['项目名称', '项目特征', '单位', '工程量'],
                    '某工程造价表.xlsx',
                )
                self.assertIsNotNone(tpl)
                self.assertGreater(score, 0.3)
            finally:
                fm.TEMPLATE_DIR = original_dir


class TestValidationEngine(unittest.TestCase):
    def test_required_field(self):
        rows = [
            {'item_name': '电力电缆', 'quantity': 100},
            {'item_name': '', 'quantity': 50},  # 空名称
        ]
        report = validate_rows(rows, use_builtin=True)
        self.assertEqual(report.total_rows, 2)
        self.assertEqual(report.error_count, 1)  # 第二行缺少必填项

    def test_quantity_positive(self):
        rows = [
            {'item_name': '电力电缆', 'quantity': 100},
            {'item_name': '控制电缆', 'quantity': -10},  # 负数
        ]
        report = validate_rows(rows, use_builtin=True)
        self.assertEqual(report.warning_count, 1)

    def test_custom_rule_regex(self):
        rows = [
            {'item_name': '电力电缆', 'gb_code': '010101001'},
            {'item_name': '控制电缆', 'gb_code': 'abc'},  # 非数字
        ]
        custom_rules = [
            create_rule(
                '编码格式', 'gb_code', 'regex',
                level=LEVEL_ERROR,
                pattern=r'^\d{9,12}$',
                message='编码应为9-12位数字',
            )
        ]
        report = validate_rows(rows, custom_rules=custom_rules, use_builtin=False)
        self.assertEqual(report.error_count, 1)

    def test_custom_rule_range(self):
        rows = [
            {'item_name': '电力电缆', 'unit_rate': 100},
            {'item_name': '控制电缆', 'unit_rate': -50},  # 负数
        ]
        custom_rules = [
            create_rule(
                '单价非负', 'unit_rate', 'range',
                level=LEVEL_WARNING,
                min=0,
            )
        ]
        report = validate_rows(rows, custom_rules=custom_rules, use_builtin=False)
        self.assertEqual(report.warning_count, 1)

    def test_can_import(self):
        rows = [{'item_name': '电力电缆', 'quantity': 100}]
        report = validate_rows(rows, use_builtin=True)
        self.assertTrue(report.can_import)

    def test_cannot_import_with_error(self):
        rows = [{'item_name': '', 'quantity': 100}]
        report = validate_rows(rows, use_builtin=True)
        self.assertFalse(report.can_import)

    def test_report_summary(self):
        rows = [
            {'item_name': '电力电缆', 'quantity': 100},
            {'item_name': '', 'quantity': -10},
        ]
        report = validate_rows(rows, use_builtin=True)
        summary = report.to_dict()
        self.assertIn('summary_by_level', summary)
        self.assertIn('summary_by_rule', summary)
        self.assertEqual(summary['error_count'], 1)

    def test_get_rule_templates(self):
        templates = get_rule_templates()
        self.assertGreater(len(templates), 0)
        # 检查是否包含必填项规则
        template_names = [t['name'] for t in templates]
        self.assertIn('项目名称必填', template_names)


class TestArchiveEnhanced(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, 'test.xlsx')
        with open(self.test_file, 'wb') as f:
            f.write(b'PK\x03\x04 test content for archive')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_calculate_file_hash(self):
        h = calculate_file_hash(self.test_file)
        self.assertEqual(len(h), 64)  # SHA256 十六进制长度

    def test_calculate_bytes_hash(self):
        h = calculate_bytes_hash(b'test data')
        self.assertEqual(len(h), 64)

    def test_compress_zip(self):
        # 用较大的内容测试压缩（小文件 ZIP 压缩后可能因文件头开销而变大）
        with open(self.test_file, 'wb') as f:
            f.write(b'PK\x03\x04 ' + b'test content ' * 1000)
        result = compress_file(self.test_file, method=COMPRESS_ZIP)
        self.assertTrue(result['ok'])
        self.assertTrue(os.path.exists(result['compressed_path']))
        self.assertEqual(result['method'], 'zip')

    def test_compress_gzip(self):
        result = compress_file(self.test_file, method=COMPRESS_GZIP)
        self.assertTrue(result['ok'])
        self.assertTrue(result['compressed_path'].endswith('.gz'))

    def test_compress_none(self):
        result = compress_file(self.test_file, method='none')
        self.assertTrue(result['ok'])
        self.assertEqual(result['compressed_path'], self.test_file)

    def test_decompress_zip(self):
        compressed = compress_file(self.test_file, method=COMPRESS_ZIP)
        extract_dir = os.path.join(self.temp_dir, 'extracted')
        result = decompress_file(compressed['compressed_path'], extract_dir)
        self.assertTrue(result['ok'])
        self.assertTrue(os.path.exists(result['extracted_path']))

    def test_archive_metadata_save_load(self):
        mgr = ArchiveMetadata(self.temp_dir)
        archive_path = os.path.join(self.temp_dir, 'test.xlsx')
        metadata = {
            'filename': 'test.xlsx',
            'file_hash': 'abc123',
            'operator': 'test_user',
            'status': 'imported',
            'row_count': 100,
        }
        self.assertTrue(mgr.save_metadata(archive_path, metadata))

        loaded = mgr.load_metadata(archive_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded['filename'], 'test.xlsx')
        self.assertEqual(loaded['operator'], 'test_user')

    def test_archive_metadata_update(self):
        mgr = ArchiveMetadata(self.temp_dir)
        archive_path = os.path.join(self.temp_dir, 'test.xlsx')
        mgr.save_metadata(archive_path, {'filename': 'test.xlsx', 'status': 'pending'})
        mgr.update_metadata(archive_path, {'status': 'imported', 'row_count': 100})

        loaded = mgr.load_metadata(archive_path)
        self.assertEqual(loaded['status'], 'imported')
        self.assertEqual(loaded['row_count'], 100)

    def test_integrity_check_ok(self):
        # 创建归档文件和元数据
        archive_path = os.path.join(self.temp_dir, 'archive_test.xlsx')
        with open(archive_path, 'wb') as f:
            f.write(b'test archive content')

        file_hash = calculate_file_hash(archive_path)
        mgr = ArchiveMetadata(self.temp_dir)
        mgr.save_metadata(archive_path, {'file_hash': file_hash})

        checker = ArchiveIntegrityChecker(self.temp_dir)
        result = checker.check_file(archive_path)
        self.assertTrue(result['ok'])
        self.assertTrue(result['hash_match'])

    def test_integrity_check_hash_mismatch(self):
        archive_path = os.path.join(self.temp_dir, 'archive_test.xlsx')
        with open(archive_path, 'wb') as f:
            f.write(b'original content')

        mgr = ArchiveMetadata(self.temp_dir)
        mgr.save_metadata(archive_path, {'file_hash': 'wrong_hash_123'})

        checker = ArchiveIntegrityChecker(self.temp_dir)
        result = checker.check_file(archive_path)
        self.assertFalse(result['ok'])
        self.assertFalse(result['hash_match'])

    def test_integrity_check_missing_file(self):
        checker = ArchiveIntegrityChecker(self.temp_dir)
        result = checker.check_file(os.path.join(self.temp_dir, 'nonexistent.xlsx'))
        self.assertFalse(result['ok'])
        self.assertFalse(result['file_exists'])

    def test_archive_search(self):
        # 创建几个归档
        for i in range(3):
            archive_path = os.path.join(self.temp_dir, f'archive_{i}.xlsx')
            with open(archive_path, 'wb') as f:
                f.write(f'content {i}'.encode())
            mgr = ArchiveMetadata(self.temp_dir)
            mgr.save_metadata(archive_path, {
                'filename': f'工程{i}.xlsx',
                'file_hash': f'hash{i}',
                'operator': 'user_a' if i < 2 else 'user_b',
                'status': 'imported',
            })

        searcher = ArchiveSearch(self.temp_dir)
        # 按操作人搜索
        results = searcher.search(operator='user_a')
        self.assertEqual(len(results), 2)

        # 按文件名搜索
        results = searcher.search(filename='工程1')
        self.assertEqual(len(results), 1)

    def test_archive_cleaner_expired(self):
        # 创建一个"过期"的归档（手动设置旧日期）
        archive_path = os.path.join(self.temp_dir, 'old_archive.xlsx')
        with open(archive_path, 'wb') as f:
            f.write(b'old content')
        mgr = ArchiveMetadata(self.temp_dir)
        mgr.save_metadata(archive_path, {
            'filename': 'old.xlsx',
            'archived_at': '2020-01-01T00:00:00+00:00',
        })

        cleaner = ArchiveCleaner(self.temp_dir, retention_days=30)
        expired = cleaner.find_expired()
        self.assertEqual(len(expired), 1)

    def test_archive_cleaner_dry_run(self):
        archive_path = os.path.join(self.temp_dir, 'old_archive.xlsx')
        with open(archive_path, 'wb') as f:
            f.write(b'old content')
        mgr = ArchiveMetadata(self.temp_dir)
        mgr.save_metadata(archive_path, {
            'filename': 'old.xlsx',
            'archived_at': '2020-01-01T00:00:00+00:00',
        })

        cleaner = ArchiveCleaner(self.temp_dir, retention_days=30)
        result = cleaner.clean_expired(dry_run=True)
        self.assertEqual(result['expired_count'], 1)
        self.assertEqual(result['deleted_count'], 0)  # dry_run 不删除
        self.assertTrue(os.path.exists(archive_path))  # 文件仍在


if __name__ == '__main__':
    unittest.main()
