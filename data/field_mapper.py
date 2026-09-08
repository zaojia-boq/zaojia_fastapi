# -*- coding: utf-8 -*-
"""M2 深化：字段映射模板（用户自定义列名→字段映射，保存模板复用）。

在 data/aliases.py 的硬编码别名映射基础上深化：
1. 用户自定义映射：用户可在导入预览时调整列名→字段的映射关系
2. 模板保存：映射关系可保存为命名模板，下次导入同名/相似格式文件时自动复用
3. 模板匹配：根据文件名模式、表头相似度自动推荐最合适的模板
4. 映射校验：校验映射的字段是否存在、是否必填、类型是否兼容
5. 映射历史：记录每次导入使用的映射模板，便于追溯

设计：
- 纯函数模式，模板存储为 JSON 文件
- 支持全局模板和项目级模板
- 模板匹配算法：表头 Jaccard 相似度 + 文件名模式匹配
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("zaojia.import")

# 标准字段定义（可映射的目标字段）
STANDARD_FIELDS = {
    'item_name': {'label': '项目名称', 'required': True, 'type': 'string', 'aliases': ['项目名称', '名称', '项目', '分项工程名称']},
    'item_feature': {'label': '项目特征', 'required': False, 'type': 'string', 'aliases': ['项目特征', '特征', '规格型号', '规格', '型号']},
    'unit': {'label': '单位', 'required': False, 'type': 'string', 'aliases': ['单位', '计量单位']},
    'quantity': {'label': '工程量', 'required': False, 'type': 'number', 'aliases': ['工程量', '数量', '工程数量']},
    'unit_rate': {'label': '综合单价', 'required': False, 'type': 'number', 'aliases': ['综合单价', '单价', '基价']},
    'total': {'label': '合价', 'required': False, 'type': 'number', 'aliases': ['合价', '总价', '金额', '综合合价']},
    'gb_code': {'label': '国标编码', 'required': False, 'type': 'string', 'aliases': ['国标编码', '编码', '项目编码', '清单编码']},
    'project_name': {'label': '工程名称', 'required': False, 'type': 'string', 'aliases': ['工程名称', '工程项目']},
    'sub_division': {'label': '分部工程', 'required': False, 'type': 'string', 'aliases': ['分部工程', '分部', '专业工程']},
    'ordinal': {'label': '序号', 'required': False, 'type': 'string', 'aliases': ['序号', '编号', 'No', 'NO']},
    'remark': {'label': '备注', 'required': False, 'type': 'string', 'aliases': ['备注', '说明', '注']},
}

# 模板存储目录
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'data' / 'import_templates'


def _ensure_template_dir():
    """确保模板存储目录存在。"""
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


def _jaccard_similarity(set1: set, set2: set) -> float:
    """计算两个集合的 Jaccard 相似度。"""
    if not set1 and not set2:
        return 1.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def auto_map_headers(headers: List[str]) -> Dict[str, str]:
    """自动映射表头到标准字段（基于别名匹配）。

    Args:
        headers: 表头列表

    Returns:
        {列名: 标准字段名}，未匹配的列不包含在结果中
    """
    mapping = {}
    used_fields = set()

    for header in headers:
        header_clean = str(header).strip()
        if not header_clean:
            continue

        best_field = None
        best_score = 0

        for field_name, field_def in STANDARD_FIELDS.items():
            if field_name in used_fields:
                continue
            # 精确匹配
            if header_clean == field_def['label']:
                best_field = field_name
                best_score = 1.0
                break
            # 别名匹配
            for alias in field_def['aliases']:
                if header_clean == alias:
                    best_field = field_name
                    best_score = 0.95
                    break
                # 包含匹配
                if alias in header_clean or header_clean in alias:
                    score = 0.7 * min(len(alias), len(header_clean)) / max(len(alias), len(header_clean))
                    if score > best_score:
                        best_field = field_name
                        best_score = score
            if best_score >= 0.95:
                break

        if best_field and best_score >= 0.5:
            mapping[header_clean] = best_field
            used_fields.add(best_field)

    return mapping


def validate_mapping(mapping: Dict[str, str], headers: List[str]) -> Dict[str, Any]:
    """校验字段映射的合法性。

    Returns:
        {
            'valid': bool,
            'errors': list[str],
            'warnings': list[str],
            'missing_required': list[str],
            'unknown_fields': list[str],
        }
    """
    errors = []
    warnings = []
    mapped_fields = set(mapping.values())

    # 检查未知字段
    unknown_fields = [f for f in mapped_fields if f not in STANDARD_FIELDS]
    if unknown_fields:
        errors.append(f'未知字段：{", ".join(unknown_fields)}')

    # 检查必填字段
    missing_required = []
    for field_name, field_def in STANDARD_FIELDS.items():
        if field_def['required'] and field_name not in mapped_fields:
            missing_required.append(field_def['label'])
    if missing_required:
        warnings.append(f'缺少必填字段映射：{", ".join(missing_required)}')

    # 检查重复映射（多个列映射到同一个字段）
    field_counts = {}
    for col, field in mapping.items():
        field_counts[field] = field_counts.get(field, 0) + 1
    duplicates = {f: c for f, c in field_counts.items() if c > 1}
    if duplicates:
        errors.append(f'重复映射（多个列映射到同一字段）：{duplicates}')

    # 检查未映射的列
    mapped_cols = set(mapping.keys())
    unmapped_cols = [h for h in headers if h and h not in mapped_cols]
    if unmapped_cols:
        warnings.append(f'未映射的列（将被忽略）：{", ".join(unmapped_cols[:10])}{"..." if len(unmapped_cols) > 10 else ""}')

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
        'missing_required': missing_required,
        'unknown_fields': unknown_fields,
    }


def save_template(
    template_name: str,
    mapping: Dict[str, str],
    headers: List[str],
    filename_pattern: str = '',
    description: str = '',
) -> Dict[str, Any]:
    """保存字段映射模板。

    Args:
        template_name: 模板名称（唯一标识）
        mapping: 列名→标准字段的映射
        headers: 表头列表（用于模板匹配）
        filename_pattern: 文件名匹配模式（正则表达式，可选）
        description: 模板描述

    Returns:
        {ok: bool, template_path: str, message: str}
    """
    _ensure_template_dir()

    # 模板名称安全处理
    safe_name = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', template_name)
    template_path = TEMPLATE_DIR / f'{safe_name}.json'

    template_data = {
        'name': template_name,
        'mapping': mapping,
        'headers': headers,
        'filename_pattern': filename_pattern,
        'description': description,
        'created_at': __import__('time').time(),
        'usage_count': 0,
    }

    try:
        template_path.write_text(json.dumps(template_data, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'ok': True, 'template_path': str(template_path), 'message': f'模板「{template_name}」已保存'}
    except Exception as e:
        return {'ok': False, 'template_path': '', 'message': f'保存模板失败：{e}'}


def load_template(template_name: str) -> Optional[Dict[str, Any]]:
    """加载字段映射模板。"""
    _ensure_template_dir()
    safe_name = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', template_name)
    template_path = TEMPLATE_DIR / f'{safe_name}.json'

    if not template_path.exists():
        return None

    try:
        data = json.loads(template_path.read_text(encoding='utf-8'))
        return data
    except Exception as e:
        logger.warning(f'加载模板失败：{e}')
        return None


def list_templates() -> List[Dict[str, Any]]:
    """列出所有已保存的模板。"""
    _ensure_template_dir()
    templates = []
    for f in TEMPLATE_DIR.glob('*.json'):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            templates.append({
                'name': data.get('name', f.stem),
                'description': data.get('description', ''),
                'filename_pattern': data.get('filename_pattern', ''),
                'usage_count': data.get('usage_count', 0),
                'created_at': data.get('created_at', 0),
                'field_count': len(data.get('mapping', {})),
            })
        except Exception:
            continue
    return sorted(templates, key=lambda x: x.get('usage_count', 0), reverse=True)


def find_best_template(
    headers: List[str],
    filename: str = '',
) -> Tuple[Optional[Dict[str, Any]], float]:
    """根据表头和文件名自动推荐最合适的模板。

    Returns:
        (template_data, similarity_score)，无匹配时返回 (None, 0.0)
    """
    templates = list_templates()
    if not templates:
        return None, 0.0

    best_template = None
    best_score = 0.0
    header_set = set(str(h).strip() for h in headers if h)

    for tpl_info in templates:
        tpl = load_template(tpl_info['name'])
        if not tpl:
            continue

        score = 0.0

        # 1. 表头相似度（权重 0.7）
        tpl_headers = set(str(h).strip() for h in tpl.get('headers', []) if h)
        header_sim = _jaccard_similarity(header_set, tpl_headers)
        score += 0.7 * header_sim

        # 2. 文件名模式匹配（权重 0.3）
        filename_pattern = tpl.get('filename_pattern', '')
        if filename_pattern and filename:
            try:
                if re.search(filename_pattern, filename, re.IGNORECASE):
                    score += 0.3
            except re.error:
                pass

        if score > best_score:
            best_score = score
            best_template = tpl

    # 相似度阈值：低于 0.3 不推荐
    if best_score < 0.3:
        return None, best_score

    return best_template, best_score


def delete_template(template_name: str) -> bool:
    """删除字段映射模板。"""
    _ensure_template_dir()
    safe_name = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', template_name)
    template_path = TEMPLATE_DIR / f'{safe_name}.json'

    if template_path.exists():
        template_path.unlink()
        return True
    return False


def apply_mapping_to_row(
    row: List[Any],
    headers: List[str],
    mapping: Dict[str, str],
) -> Dict[str, Any]:
    """将字段映射应用到一行数据，输出标准字段字典。

    Args:
        row: 一行数据（列表）
        headers: 表头列表
        mapping: 列名→标准字段的映射

    Returns:
        {标准字段名: 值}
    """
    result = {}
    for col_idx, header in enumerate(headers):
        header_clean = str(header).strip() if header else ''
        if header_clean in mapping and col_idx < len(row):
            field_name = mapping[header_clean]
            result[field_name] = row[col_idx]
    return result
