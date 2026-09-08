# -*- coding: utf-8 -*-
"""M2 深化：导入校验规则引擎（可配置的数据质量校验规则）。

在 import_service.py 的基础必填校验基础上深化：
1. 可配置规则：用户可定义校验规则（类型/值域/格式/重复/必填）
2. 规则模板：内置常用规则模板，可一键启用
3. 批量校验：对解析后的数据批量执行校验，输出校验报告
4. 错误分级：error（阻断导入）/ warning（警告但可导入）/ info（信息）
5. 异常行定位：精确定位到行号、列名、错误原因
6. 校验结果统计：按规则、按错误类型统计，生成数据质量报告

设计：
- 纯函数模式，规则定义为数据（JSON），非代码
- 支持自定义规则（通过配置文件）
- 校验结果可序列化（用于前端展示和审计）
"""
import re
from typing import Optional, Dict, Any, List, Callable


# 校验错误级别
LEVEL_ERROR = 'error'      # 阻断导入
LEVEL_WARNING = 'warning'  # 警告但可导入
LEVEL_INFO = 'info'        # 信息

# 内置规则模板
BUILTIN_RULES = {
    'required_item_name': {
        'name': '项目名称必填',
        'field': 'item_name',
        'type': 'required',
        'level': LEVEL_ERROR,
        'message': '项目名称不能为空',
        'enabled': True,
    },
    'quantity_positive': {
        'name': '工程量必须为正数',
        'field': 'quantity',
        'type': 'range',
        'level': LEVEL_WARNING,
        'min': 0,
        'exclusive_min': True,
        'message': '工程量应为正数',
        'enabled': True,
    },
    'unit_rate_nonnegative': {
        'name': '综合单价非负',
        'field': 'unit_rate',
        'type': 'range',
        'level': LEVEL_WARNING,
        'min': 0,
        'message': '综合单价不应为负数',
        'enabled': True,
    },
    'gb_code_format': {
        'name': '国标编码格式校验',
        'field': 'gb_code',
        'type': 'regex',
        'level': LEVEL_WARNING,
        'pattern': r'^\d{9,12}$',
        'message': '国标编码应为9-12位数字',
        'enabled': False,
    },
    'total_consistency': {
        'name': '合价=工程量×单价',
        'field': 'total',
        'type': 'formula',
        'level': LEVEL_WARNING,
        'formula': 'total ≈ quantity * unit_rate',
        'tolerance': 0.01,  # 1% 容差
        'message': '合价与工程量×单价不一致',
        'enabled': False,
    },
    'no_duplicate_item': {
        'name': '清单项不重复',
        'field': 'item_name',
        'type': 'unique',
        'level': LEVEL_INFO,
        'message': '存在重复的清单项名称',
        'enabled': False,
    },
    'unit_standard': {
        'name': '单位标准化校验',
        'field': 'unit',
        'type': 'enum',
        'level': LEVEL_INFO,
        'allowed': ['m', 'm2', 'm3', 'kg', 't', '个', '套', '组', '台', '樘', 'm²', 'm³', '吨', '米', '平方米', '立方米'],
        'message': '单位不在标准单位列表中',
        'enabled': False,
    },
}


class ValidationResult:
    """校验结果（单行）。"""

    def __init__(self, row_index: int, field: str, rule_name: str, level: str, message: str, value: Any = None):
        self.row_index = row_index
        self.field = field
        self.rule_name = rule_name
        self.level = level
        self.message = message
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            'row_index': self.row_index,
            'field': self.field,
            'rule_name': self.rule_name,
            'level': self.level,
            'message': self.message,
            'value': str(self.value) if self.value is not None else None,
        }


class ValidationReport:
    """校验报告（全量）。"""

    def __init__(self):
        self.results: List[ValidationResult] = []
        self.total_rows = 0
        self.valid_rows = 0
        self.error_rows = set()
        self.warning_rows = set()

    def add_result(self, result: ValidationResult):
        self.results.append(result)
        if result.level == LEVEL_ERROR:
            self.error_rows.add(result.row_index)
        elif result.level == LEVEL_WARNING:
            self.warning_rows.add(result.row_index)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.level == LEVEL_ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.results if r.level == LEVEL_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for r in self.results if r.level == LEVEL_INFO)

    @property
    def can_import(self) -> bool:
        """是否可以导入（无 error 级别错误）。"""
        return self.error_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_rows': self.total_rows,
            'valid_rows': self.valid_rows,
            'error_count': self.error_count,
            'warning_count': self.warning_count,
            'info_count': self.info_count,
            'error_rows': sorted(list(self.error_rows)),
            'warning_rows': sorted(list(self.warning_rows)),
            'can_import': self.can_import,
            'results': [r.to_dict() for r in self.results],
            'summary_by_rule': self._summary_by_rule(),
            'summary_by_level': {
                'error': self.error_count,
                'warning': self.warning_count,
                'info': self.info_count,
            },
        }

    def _summary_by_rule(self) -> Dict[str, Dict[str, int]]:
        """按规则统计。"""
        summary = {}
        for r in self.results:
            if r.rule_name not in summary:
                summary[r.rule_name] = {'error': 0, 'warning': 0, 'info': 0}
            summary[r.rule_name][r.level] += 1
        return summary


def _to_float(value: Any) -> Optional[float]:
    """安全转换为浮点数。"""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _validate_required(row: Dict[str, Any], rule: Dict[str, Any], row_index: int) -> Optional[ValidationResult]:
    """必填校验。"""
    field = rule['field']
    value = row.get(field)
    if value is None or str(value).strip() == '':
        return ValidationResult(row_index, field, rule['name'], rule['level'], rule['message'], value)
    return None


def _validate_range(row: Dict[str, Any], rule: Dict[str, Any], row_index: int) -> Optional[ValidationResult]:
    """值域校验。"""
    field = rule['field']
    value = _to_float(row.get(field))
    if value is None:
        return None  # 空值由 required 规则处理

    if 'min' in rule:
        if rule.get('exclusive_min', False):
            if value <= rule['min']:
                return ValidationResult(row_index, field, rule['name'], rule['level'], rule['message'], value)
        else:
            if value < rule['min']:
                return ValidationResult(row_index, field, rule['name'], rule['level'], rule['message'], value)

    if 'max' in rule:
        if rule.get('exclusive_max', False):
            if value >= rule['max']:
                return ValidationResult(row_index, field, rule['name'], rule['level'], rule['message'], value)
        else:
            if value > rule['max']:
                return ValidationResult(row_index, field, rule['name'], rule['level'], rule['message'], value)

    return None


def _validate_regex(row: Dict[str, Any], rule: Dict[str, Any], row_index: int) -> Optional[ValidationResult]:
    """正则格式校验。"""
    field = rule['field']
    value = row.get(field)
    if value is None or str(value).strip() == '':
        return None  # 空值由 required 规则处理

    if not re.match(rule['pattern'], str(value)):
        return ValidationResult(row_index, field, rule['name'], rule['level'], rule['message'], value)
    return None


def _validate_enum(row: Dict[str, Any], rule: Dict[str, Any], row_index: int) -> Optional[ValidationResult]:
    """枚举值校验。"""
    field = rule['field']
    value = row.get(field)
    if value is None or str(value).strip() == '':
        return None

    if str(value).strip() not in rule.get('allowed', []):
        return ValidationResult(row_index, field, rule['name'], rule['level'], rule['message'], value)
    return None


def _validate_formula(row: Dict[str, Any], rule: Dict[str, Any], row_index: int) -> Optional[ValidationResult]:
    """公式校验（如 total ≈ quantity * unit_rate）。"""
    field = rule['field']
    total = _to_float(row.get('total'))
    quantity = _to_float(row.get('quantity'))
    unit_rate = _to_float(row.get('unit_rate'))

    if total is None or quantity is None or unit_rate is None:
        return None

    expected = quantity * unit_rate
    if expected == 0:
        return None

    tolerance = rule.get('tolerance', 0.01)
    diff_ratio = abs(total - expected) / abs(expected)
    if diff_ratio > tolerance:
        return ValidationResult(
            row_index, field, rule['name'], rule['level'],
            f"{rule['message']}（计算值={expected:.2f}，实际值={total:.2f}，差异={diff_ratio:.2%}）",
            total,
        )
    return None


# 规则类型 → 校验函数映射
RULE_VALIDATORS: Dict[str, Callable] = {
    'required': _validate_required,
    'range': _validate_range,
    'regex': _validate_regex,
    'enum': _validate_enum,
    'formula': _validate_formula,
}


def validate_rows(
    rows: List[Dict[str, Any]],
    custom_rules: Optional[List[Dict[str, Any]]] = None,
    use_builtin: bool = True,
) -> ValidationReport:
    """批量校验数据行。

    Args:
        rows: 数据行列表（已映射为标准字段字典）
        custom_rules: 自定义规则列表
        use_builtin: 是否使用内置规则

    Returns:
        ValidationReport 校验报告
    """
    report = ValidationReport()
    report.total_rows = len(rows)

    # 收集规则
    rules = []
    if use_builtin:
        for rule in BUILTIN_RULES.values():
            if rule.get('enabled', False):
                rules.append(rule)
    if custom_rules:
        rules.extend(custom_rules)

    if not rules:
        report.valid_rows = len(rows)
        return report

    # 逐行校验
    for row_idx, row in enumerate(rows):
        row_has_error = False
        for rule in rules:
            validator = RULE_VALIDATORS.get(rule['type'])
            if not validator:
                continue
            result = validator(row, rule, row_idx)
            if result:
                report.add_result(result)
                if result.level == LEVEL_ERROR:
                    row_has_error = True
        if not row_has_error:
            report.valid_rows += 1

    return report


def get_rule_templates() -> List[Dict[str, Any]]:
    """获取所有内置规则模板（含启用状态）。"""
    return [dict(rule) for rule in BUILTIN_RULES.values()]


def create_rule(
    name: str,
    field: str,
    rule_type: str,
    level: str = LEVEL_WARNING,
    message: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """创建自定义规则。"""
    rule = {
        'name': name,
        'field': field,
        'type': rule_type,
        'level': level,
        'message': message or f'{field} 校验失败',
        'enabled': True,
    }
    rule.update(kwargs)
    return rule
