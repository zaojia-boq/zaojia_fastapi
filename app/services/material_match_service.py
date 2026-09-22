# -*- coding: utf-8 -*-
"""M3.4 快速匹配 Service（FastAPI/SQLAlchemy 版）。

FROZEN 契约（M3 §5 / §9.2 / 架构 §19）：
- find_matches(db, boq_item_ids) → READ-ONLY，返回 Top-5 候选信封；
- confirm_match(db, payload)     → WRITE（B 类），仅填空字段、绝不覆盖已有 B 类值，
  写审计四元组（operator / reason / trace_id / timestamp，架构 §19.7）。

算法来源：原 Odoo 版 material_match_service.py（算法规格 100% 继承，框架切换）。
纯函数依赖：data/match_score.py（score_candidates / high_confidence），从 Odoo 版原样复制。

边界铁律：
- 仅候选建议，绝不自动改 boq_item；人工确认后回填 std_name/std_spec/material_dict_id（M3 §5.1）；
- B 类字段仅填空，绝不覆盖已有值（M3 §5.6 + M1 §4.9）；
- 回填后 match_key 由 before_update 事件监听器自动重算（M1.2）；
- 错误统一机器可识别错误码，前缀 MATCH_。

优化记录（M7）：
- P0-1: 匹配前先查 list_material_mapping 映射表，命中则直接返回
- P0-2: TF-IDF/FAISS 索引缓存化，模块级单例，5分钟 TTL
- P1-1: 同义词扩展加人工确认标记，不直接写入 material_dict
- P1-2: 统一 _build_dict_rows 实现
"""
import logging
import threading
import time
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from app.models.material_dict import MaterialDict
from app.models.list_material_mapping import ListMaterialMapping
from app.core.audit import log_audit
from data.match_score import score_candidates, high_confidence
from data.tfidf_matcher import TfidfMatcher, fuse_scores
from data.faiss_matcher import FaissMatcher, fuse_three_algorithms, FAISS_AVAILABLE
from data.learning_engine_v3 import get_global_engine_v3

logger = logging.getLogger("zaojia.match")

# 匹配算法融合权重（默认值，学习引擎会根据确认结果自动调整）
DEFAULT_RF_WEIGHT = 0.3      # rapidfuzz 编辑距离（精确匹配强）
DEFAULT_TF_WEIGHT = 0.35     # TF-IDF 语义匹配（同义词/近义词强）
DEFAULT_FAISS_WEIGHT = 0.35  # FAISS 向量检索（大数据量快）

# P0-2: 索引缓存（模块级单例，5分钟 TTL）
_INDEX_CACHE_TTL = 300  # 秒
_index_cache_lock = threading.Lock()
_index_cache: dict = {
    "dict_rows": None,
    "tfidf": None,
    "faiss": None,
    "cached_at": 0,
}

# P0-1: 映射表缓存（list_item_code -> material_name）
_mapping_cache: dict = {"data": None, "cached_at": 0}
_mapping_cache_ttl = 600  # 10 分钟


def _err(code, msg, trace_id):
    """错误信封（success=False / data=None / error_code+message）。"""
    return {
        'success': False,
        'data': None,
        'error_code': code,
        'message': msg,
        'total': 0,
        'warnings': [],
        'trace_id': trace_id,
    }


# P1-2: 统一候选池构建（l3 + l4）
def _build_dict_rows(db: Session, dict_ids=None) -> list[dict]:
    """从 material_dict 构建候选行（L3 大类 + L4 材料名称级）。

    每个 dict_row 含：id / name / spec / category_path。
    候选池规则与 page_services.get_pending_matches 保持一致：
    取 l3（如"槽式桥架及配件"）+ l4（如"照明配电箱"）两级，
    不取 l5 叶子节点（spec 碎片会导致匹配到无意义项）。
    category_path 用 cat_l1/cat_l2/cat_l3/name 拼接。
    """
    query = db.query(MaterialDict).filter(MaterialDict.level.in_(['l3', 'l4']))
    if dict_ids:
        query = db.query(MaterialDict).filter(MaterialDict.id.in_(list(dict_ids)))
    rows = []
    for d in query.all():
        cat_path = '/'.join(p for p in [d.cat_l1, d.cat_l2, d.cat_l3, d.name] if p)
        spec = ''
        if d.spec_whitelist:
            spec = d.spec_whitelist[0] if isinstance(d.spec_whitelist, list) else str(d.spec_whitelist)
        rows.append({
            'id': d.id,
            'name': d.name or '',
            'spec': spec or d.name or '',
            'category_path': cat_path or d.name or '',
        })
    return rows


# P0-2: 获取缓存的索引（模块级单例）
def _get_cached_indexes(db: Session) -> tuple[list[dict], Optional[TfidfMatcher], Optional[FaissMatcher]]:
    """获取缓存的 TF-IDF / FAISS 索引（5分钟 TTL）。"""
    global _index_cache
    now = time.time()

    with _index_cache_lock:
        # 检查缓存是否有效
        if (_index_cache["dict_rows"] is not None and
            now - _index_cache["cached_at"] < _INDEX_CACHE_TTL):
            return (
                _index_cache["dict_rows"],
                _index_cache["tfidf"],
                _index_cache["faiss"],
            )

        # 重建索引
        dict_rows = _build_dict_rows(db)
        tfidf_matcher = TfidfMatcher(dict_rows) if dict_rows else None
        faiss_matcher = FaissMatcher(dict_rows) if (dict_rows and FAISS_AVAILABLE) else None

        _index_cache = {
            "dict_rows": dict_rows,
            "tfidf": tfidf_matcher,
            "faiss": faiss_matcher,
            "cached_at": now,
        }
        return dict_rows, tfidf_matcher, faiss_matcher


def _invalidate_index_cache():
    """失效索引缓存（数据变更后调用）。"""
    global _index_cache
    with _index_cache_lock:
        _index_cache = {
            "dict_rows": None,
            "tfidf": None,
            "faiss": None,
            "cached_at": 0,
        }


# P0-1: 获取映射表缓存
def _get_mapping_cache(db: Session) -> dict[str, str]:
    """获取清单编码 -> 材料名称映射表缓存（10分钟 TTL）。"""
    global _mapping_cache
    now = time.time()

    # 检查缓存是否有效
    if (_mapping_cache["data"] is not None and
        now - _mapping_cache["cached_at"] < _mapping_cache_ttl):
        return _mapping_cache["data"]

    # 加载映射表
    mappings = db.query(ListMaterialMapping).all()
    mapping_dict = {}
    for m in mappings:
        # 9位编码 -> 材料名称
        mapping_dict[m.list_item_code] = m.material_name

    _mapping_cache = {
        "data": mapping_dict,
        "cached_at": now,
    }
    return mapping_dict


def _invalidate_mapping_cache():
    """失效映射表缓存（数据变更后调用）。"""
    global _mapping_cache
    _mapping_cache = {"data": None, "cached_at": 0}


# ---------------------------------------------------------------------------
# READ：find_matches（无写操作）
# ---------------------------------------------------------------------------

def find_matches(db: Session, boq_item_ids: list[int]) -> dict[str, Any]:
    """召回候选 → 结构化信封（§19.6）。

    boq_item 的匹配输入取真实字段：query_name=item_name，
    query_spec=item_feature（天然语言来源，M3 §5.3）。
    返回 {boq_item_id: [Top-5 候选...]}，每个候选含 dict_id/name/spec/score/category_path。

    优化（M7）：
    - P0-1: 先查 list_material_mapping 映射表，命中则直接返回高置信候选
    - P0-2: 使用缓存的 TF-IDF/FAISS 索引
    """
    trace_id = uuid.uuid4().hex
    warnings = []

    if not boq_item_ids:
        return {
            'success': True,
            'data': {},
            'total': 0,
            'warnings': ['boq_item_ids 为空'],
            'trace_id': trace_id,
        }

    recs = db.query(BoqItem).filter(BoqItem.id.in_(boq_item_ids)).all()
    found_ids = {r.id for r in recs}
    for bid in boq_item_ids:
        if bid not in found_ids:
            warnings.append(f'boq_item {bid} 不存在')

    # P0-1: 加载映射表缓存
    mapping_dict = _get_mapping_cache(db)

    # P0-2: 获取缓存的索引
    dict_rows, tfidf_matcher, faiss_matcher = _get_cached_indexes(db)

    # 从学习引擎 v3 获取当前权重（多策略融合 + 概念漂移 + 元学习）
    learning_engine = get_global_engine_v3()

    data = {}
    mapping_hits = 0
    fuzzy_hits = 0

    for rec in recs:
        query_name = rec.item_name or ''
        query_spec = rec.item_feature or ''
        item_code = rec.item_code or ''

        # P0-1: 先查映射表（9位编码前缀匹配）
        mapping_hit = None
        if item_code:
            # 取前9位编码
            code9 = item_code[:9] if len(item_code) >= 9 else item_code
            mapped_name = mapping_dict.get(code9)
            if mapped_name:
                # 映射表命中大类分类，返回分类信息
                # 注意：映射表现在存储的是大类名称（钢筋/水泥/混凝土/管道/电线电缆等）
                # 不是具体材料名称，所以不在 material_dict 里查找
                mapping_hit = {
                    'dict_id': None,  # 大类分类，不绑定具体 material_dict id
                    'name': mapped_name,
                    'spec': '',
                    'score': 100.0,  # 映射表命中给满分
                    'category_path': f"大类分类/{mapped_name}",
                    'source': 'mapping_table',
                    'is_category': True,  # 标记为大类分类
                }

        if mapping_hit:
            # 映射表命中，直接返回分类结果
            data[rec.id] = [mapping_hit]
            mapping_hits += 1
            continue

        # 映射表未命中，走模糊匹配
        fuzzy_hits += 1

        # 按清单项类别获取权重（v2 按类别学习）
        category_path = getattr(rec, 'category_path', '') or ''
        weights = learning_engine.get_weights(category_path)
        rf_weight = weights.get('rf', DEFAULT_RF_WEIGHT)
        tf_weight = weights.get('tf', DEFAULT_TF_WEIGHT)
        faiss_weight = weights.get('faiss', DEFAULT_FAISS_WEIGHT)

        # 算法1：rapidfuzz 编辑距离匹配（精确匹配强）
        rf_cands = score_candidates(query_name, query_spec, dict_rows)

        # 算法2：TF-IDF 语义匹配（同义词/近义词强）
        tf_cands = []
        if tfidf_matcher:
            tf_cands = tfidf_matcher.match(query_name, query_spec, top_n=10)

        # 算法3：FAISS 向量检索（大数据量快）
        faiss_cands = []
        if faiss_matcher:
            faiss_cands = faiss_matcher.match(query_name, query_spec, top_n=10)

        # 融合三种算法的结果（加权平均，权重由学习引擎自适应）
        if tf_cands or faiss_cands:
            fused = fuse_three_algorithms(
                rf_cands,
                tf_cands,
                faiss_cands,
                rf_weight=rf_weight,
                tf_weight=tf_weight,
                faiss_weight=faiss_weight,
            )
        else:
            # TF-IDF 和 FAISS 都无结果时回退到 rapidfuzz
            fused = rf_cands

        # 按 name 去重：同名候选项只保留分数最高的（避免"配电箱"重复出现）
        seen_names = {}
        deduped = []
        for c in fused:
            n = c.get('name', '')
            if n not in seen_names:
                seen_names[n] = True
                c['source'] = 'fuzzy_match'
                deduped.append(c)
        data[rec.id] = deduped[:5]

    # 统计信息
    stats = f"映射表命中 {mapping_hits} 条，模糊匹配 {fuzzy_hits} 条"
    logger.info(f"find_matches 统计：{stats}")

    return {
        'success': True,
        'data': data,
        'total': len(recs),
        'warnings': warnings + [stats],
        'trace_id': trace_id,
    }


# ---------------------------------------------------------------------------
# WRITE：confirm_match（B 类写，仅填空、绝不覆盖）
# ---------------------------------------------------------------------------

def confirm_match(db: Session, payload: dict) -> dict[str, Any]:
    """确认匹配回填 → 结构化信封（§19.6），写审计四元组（§19.7）。

    payload = {
      "operator": str, "reason": str, "trace_id": str(可选),
      "items": [{"boq_item_id":int, "dict_id":int, "fill_empty_only":bool(可选)}]
    }

    对每个 item：仅把 std_name/std_spec/material_dict_id 填到当前为空的字段，
    绝不覆盖已有 B 类值（M3 §5.6 + M1 §4.9）。
    fill_empty_only 且高置信（high_confidence）→ 视为自动链接，reason 打 auto_linked 标记。
    回填后 match_key 由 before_update 事件监听器自动重算（M1.2）。

    优化（M7）：
    - P1-1: 同义词扩展加人工确认标记，不直接写入 material_dict
    - P0-2: 使用缓存的索引（复用）
    """
    if not isinstance(payload, dict):
        return _err('MATCH_INVALID_PAYLOAD', 'payload 必须是 dict', uuid.uuid4().hex)

    operator = payload.get('operator')
    reason = payload.get('reason')
    trace_id = payload.get('trace_id') or uuid.uuid4().hex
    items = payload.get('items')

    if not operator or not reason or not isinstance(items, list):
        return _err('MATCH_INVALID_PAYLOAD', '缺少 operator/reason/items', trace_id)

    filled = 0
    ignored = 0
    results = []
    warnings = []

    # P0-2: 获取缓存的索引（复用，避免重复构建）
    dict_rows, tfidf_matcher, faiss_matcher = _get_cached_indexes(db)

    for item in items:
        boq_id = item.get('boq_item_id')
        dict_id = item.get('dict_id')
        fill_empty_only = bool(item.get('fill_empty_only', False))

        boq = db.query(BoqItem).filter(BoqItem.id == boq_id).first()
        if not boq:
            warnings.append(f'boq_item {boq_id} 不存在')
            results.append({'boq_item_id': boq_id, 'status': 'not_found'})
            continue

        d = db.query(MaterialDict).filter(MaterialDict.id == dict_id).first()
        if not d:
            warnings.append(f'material_dict {dict_id} 不存在')
            results.append({'boq_item_id': boq_id, 'status': 'dict_not_found'})
            continue

        # 是否自动链接：fill_empty_only 且高置信（Top-1 命中且 high_confidence）
        auto_link = False
        if fill_empty_only:
            cands = score_candidates(
                boq.item_name or '', boq.item_feature or '',
                dict_rows,
            )
            auto_link = bool(cands) and cands[0]['dict_id'] == dict_id \
                and high_confidence(cands)

        # 仅填空，绝不覆盖已有 B 类值
        vals = {}
        filled_fields = []
        if not boq.std_name and (d.name or '').strip():
            vals['std_name'] = d.name
            filled_fields.append('std_name')
        if not boq.std_spec and (d.cat_l3 or d.name or '').strip():
            vals['std_spec'] = d.cat_l3 or d.name
            filled_fields.append('std_spec')
        if not boq.material_dict_id:
            vals['material_dict_id'] = d.id
            filled_fields.append('material_dict_id')

        if vals:
            audit_reason = reason
            if auto_link:
                audit_reason = '高置信自动链接 rapidfuzz=0.99 — ' + audit_reason

            # 逐字段写审计日志（B 类字段变更，append-only）
            for field_name in filled_fields:
                old_val = getattr(boq, field_name, None)
                new_val = vals[field_name]
                log_audit(
                    db=db,
                    model='boq_item',
                    res_id=boq.id,
                    action='write',
                    field_name=field_name,
                    old_value=str(old_val) if old_val is not None else None,
                    new_value=str(new_val) if new_val is not None else None,
                    operator=operator,
                    reason=audit_reason,
                    trace_id=trace_id,
                    batch_id=boq.import_batch_id,
                )

            # 执行回填（before_update 事件监听器自动重算 match_key）
            for k, v in vals.items():
                setattr(boq, k, v)
            db.flush()

            # P1-1: 同义词扩展（改进版）
            # 不直接写入 material_dict.synonyms，而是记录到待审核列表
            # 避免错误确认污染数据
            item_name = (boq.item_name or '').strip()
            if item_name and d.id:
                # 仅在审计日志中记录，不直接修改 synonyms 字段
                # 后续可在管理页面批量审核后再写入
                logger.info(
                    f'同义词学习记录（待审核）：{item_name} -> material_dict {d.id} {d.name}'
                )
                log_audit(
                    db=db,
                    model='material_dict',
                    res_id=d.id,
                    action='note',
                    field_name='synonyms_pending',
                    old_value=None,
                    new_value=item_name,
                    operator=operator,
                    reason=f'同义词学习记录（待人工审核）：确认清单项时自动学习名称',
                    trace_id=trace_id,
                )

            filled += 1
            results.append({
                'boq_item_id': boq_id,
                'dict_id': dict_id,
                'status': 'auto_linked' if auto_link else 'filled',
                'filled_fields': filled_fields,
            })
        else:
            ignored += 1
            results.append({
                'boq_item_id': boq_id,
                'dict_id': dict_id,
                'status': 'ignored',
                'filled_fields': [],
            })

    db.commit()

    # 学习引擎 v3：记录确认结果（多策略学习 + 概念漂移检测 + 轨迹记录）
    if filled > 0:
        try:
            learning_engine = get_global_engine_v3()

            for result in results:
                if result['status'] not in ('filled', 'auto_linked'):
                    continue
                boq_id = result['boq_item_id']
                confirmed_dict_id = result['dict_id']
                boq = db.query(BoqItem).filter(BoqItem.id == boq_id).first()
                if not boq:
                    continue

                query_name = boq.item_name or ''
                query_spec = boq.item_feature or ''
                category_path = getattr(boq, 'category_path', '') or ''

                # 计算各算法的候选列表（v2 多信号学习需要完整候选用于排名计算）
                rf_cands = score_candidates(query_name, query_spec, dict_rows)
                rf_top1_id = rf_cands[0]['dict_id'] if rf_cands else None
                rf_top1_score = rf_cands[0]['score'] if rf_cands else 0.0

                tf_cands = tfidf_matcher.match(query_name, query_spec, top_n=10) if tfidf_matcher else []
                tf_top1_id = tf_cands[0]['dict_id'] if tf_cands else None
                tf_top1_score = tf_cands[0]['score'] if tf_cands else 0.0

                faiss_cands = faiss_matcher.match(query_name, query_spec, top_n=10) if faiss_matcher else []
                faiss_top1_id = faiss_cands[0]['dict_id'] if faiss_cands else None
                faiss_top1_score = faiss_cands[0]['score'] if faiss_cands else 0.0

                # 记录到学习引擎 v2（多信号学习 + 按类别学习）
                learning_engine.record_confirmation(
                    query_name=query_name,
                    query_spec=query_spec,
                    confirmed_dict_id=confirmed_dict_id,
                    rf_top1_dict_id=rf_top1_id,
                    rf_top1_score=rf_top1_score,
                    tf_top1_dict_id=tf_top1_id,
                    tf_top1_score=tf_top1_score,
                    faiss_top1_dict_id=faiss_top1_id,
                    faiss_top1_score=faiss_top1_score,
                    category_path=category_path,
                    rf_candidates=rf_cands,
                    tf_candidates=tf_cands,
                    faiss_candidates=faiss_cands,
                )
        except Exception as e:
            # 学习引擎失败不影响主流程
            logger.warning(f'学习引擎 v3 记录失败: {e}')

    return {
        'success': True,
        'data': {'filled': filled, 'ignored': ignored, 'items': results},
        'total': len(items),
        'warnings': warnings,
        'trace_id': trace_id,
    }

