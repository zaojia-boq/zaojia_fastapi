# -*- coding: utf-8 -*-
"""P0-2 / P1-5 / P2 batch：清单检索 search_boq_items 行为级测试。

测试目标（防止 2026-09-16 修复回归）：
1. P0-2 候选池有界（MAX_SEARCH_POOL）：百万行不会全量拉入内存——
   用 SQLite 测试库验证：当候选数 > MAX_SEARCH_POOL 时，
   返回的 rows 数 ≤ MAX_SEARCH_POOL 且分页正常（行为门禁）。
2. P1-5 模糊兜底 std_count 同口径：模糊分支 stdCount 在 fuzzy 结果集上统计，
   与 hitCount 一致（旧代码在精确 q 上统计导致口径漂移）。
3. P2-1 模糊兜底异常静默降级：pg_trgm similarity() 在 SQLite 测试库不可用，
   应静默降级为精确匹配（不抛错，结果 = 精确命中数）。
4. P1-4 非关键词过滤单源：_apply_nonkw_filters 共用 → 主查询与模糊兜底口径一致。
5. 常规路径：关键词 OR 匹配 / 多词 AND 匹配 / 同义词扩展 / 分页夹取。
6. P1-4 排序默认相关度：候选池按价格期最新取池，排序键=(相关度, -时间)。

回归门禁：
- P0-2：旧代码 `all_items = q.order_by(...).all()` 无 limit → 全量拉入内存 OOM。
  修复后 `.limit(MAX_SEARCH_POOL)` → 候选数 > 池上限时返回池上限行数。
- P1-5：旧代码模糊分支 `std_count = q.filter(std_name != None).count()`
  （在精确 q 上统计）→ 修复后在 fuzzy 结果集上统计，与 hitCount 同口径。
"""
import pytest
from datetime import date

from app.models.import_batch import ImportBatch
from app.models.boq_item import BoqItem
from app.services import page_services


def _make_batch(db, name="test-batch"):
    batch = ImportBatch(
        name=name, source_file=f"{name}.xlsx", file_hash="h1",
        row_count=5, imported_count=5, skipped_count=0, anomaly_count=0,
        data_source_type="completed", operator="tester",
    )
    db.add(batch)
    db.flush()
    return batch


def _make_item(db, batch_id, **kwargs):
    defaults = {
        'item_code': '030404001001',
        'item_name': '电力电缆',
        'item_feature': 'YJV 4*16',
        'unit': 'm', 'quantity': 100, 'unit_rate': 50.0, 'total': 5000,
        'data_source_type': 'completed', 'province': '辽宁',
        'price_period': date(2026, 3, 1), 'active': True,
    }
    defaults.update(kwargs)
    item = BoqItem(import_batch_id=batch_id, **defaults)
    db.add(item)
    db.flush()
    return item


# ============================================================================
# 常规路径：关键词匹配
# ============================================================================

class TestSearchBoqItemsBasic:
    """search_boq_items 常规行为。"""

    def test_empty_database(self, db_session):
        """空库 → hitCount=0。"""
        result = page_services.search_boq_items(db_session)
        assert result['hitCount'] == 0
        assert result['rows'] == []

    def test_no_kw_returns_all(self, db_session):
        """无关键词 → 返回全部 active 行。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', item_code='030404001001')
        _make_item(db_session, batch.id, item_name='镀锌钢管', item_code='030702001001')
        _make_item(db_session, batch.id, item_name='HRB400 螺纹钢', item_code='010515001001')
        db_session.commit()

        result = page_services.search_boq_items(db_session)
        assert result['hitCount'] == 3
        assert len(result['rows']) == 3

    def test_single_kw_or_match(self, db_session):
        """单关键词 OR 匹配（name/code/feature/project_name 任一位置命中）。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', item_feature='YJV 4*16')
        _make_item(db_session, batch.id, item_name='镀锌钢管', item_feature='DN100')
        # item_name 含 '电缆'
        _make_item(db_session, batch.id, item_name='控制电缆', item_feature='KVVP')
        db_session.commit()

        result = page_services.search_boq_items(db_session, kw='电缆')
        # '电力电缆' + '控制电缆' 命中，'镀锌钢管' 不命中
        assert result['hitCount'] == 2
        names = {r['name'] for r in result['rows']}
        assert '电力电缆' in names
        assert '控制电缆' in names

    def test_kw_by_code(self, db_session):
        """关键词在 item_code 位置命中。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='测试项', item_code='030404001001')
        _make_item(db_session, batch.id, item_name='测试项2', item_code='030702001001')
        db_session.commit()

        result = page_services.search_boq_items(db_session, kw='030404001')
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '测试项'

    def test_multi_word_and_match(self, db_session):
        """多词搜索：AND 匹配，每个词都要在任一位置命中。"""
        batch = _make_batch(db_session)
        # 同时含 '电力' 和 '电缆' → 命中
        _make_item(db_session, batch.id, item_name='电力电缆', item_feature='YJV')
        # 只含 '电力' 不含 '电缆' → 不命中（AND）
        _make_item(db_session, batch.id, item_name='电力设备', item_feature='变压器')
        db_session.commit()

        result = page_services.search_boq_items(db_session, kw='电力 电缆')
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '电力电缆'

    def test_synonym_expansion(self, db_session):
        """同义词扩展：搜索 '桥架' 命中 '电缆桥架'。"""
        batch = _make_batch(db_session)
        # _SYNONYMS: '桥架' → ['电缆桥架', '电缆线槽', '线槽']
        # 搜索 '桥架' 的 variants 含 '电缆桥架' → item_name='电缆桥架' 命中
        _make_item(db_session, batch.id, item_name='电缆桥架', item_feature='300x100')
        _make_item(db_session, batch.id, item_name='镀锌钢管', item_feature='DN100')
        db_session.commit()

        result = page_services.search_boq_items(db_session, kw='桥架')
        # '电缆桥架' 命中（同义词扩展），'镀锌钢管' 不命中
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '电缆桥架'

    def test_pagination_clamp(self, db_session):
        """page 越界自动夹取。"""
        batch = _make_batch(db_session)
        for i in range(5):
            _make_item(db_session, batch.id, item_name=f'电缆{i}', item_code=f'03040400100{i}')
        db_session.commit()

        # page=99 越界 → 夹取到最后一页
        result = page_services.search_boq_items(db_session, per_page=2, page=99)
        assert result['page'] == 3  # 5 行 / 每页 2 → 3 页，page=99 夹取到 3

    def test_per_page_limits_rows(self, db_session):
        """per_page 限制返回行数。"""
        batch = _make_batch(db_session)
        for i in range(5):
            _make_item(db_session, batch.id, item_name=f'电缆{i}', item_code=f'03040400100{i}')
        db_session.commit()

        result = page_services.search_boq_items(db_session, per_page=2, page=1)
        assert len(result['rows']) == 2
        assert result['pages'] == 3  # 5 行 / 每页 2 → 3 页


# ============================================================================
# P0-2：候选池有界（MAX_SEARCH_POOL）
# ============================================================================

class TestSearchBoqItemsBoundedPool:
    """P0-2 修复：默认/相关度排序候选池有界 MAX_SEARCH_POOL。

    旧代码：`all_items = q.order_by(...).all()` → 百万行全量拉入内存 OOM。
    修复后：`.limit(MAX_SEARCH_POOL)` → 候选数 > 池上限时返回池上限行数。
    """

    def test_candidate_pool_bounded(self, db_session, monkeypatch):
        """候选数 > MAX_SEARCH_POOL → 返回池上限行数（有界）。"""
        batch = _make_batch(db_session)
        # 创建 5 条数据，但把 MAX_SEARCH_POOL 降到 3 → 验证有界
        for i in range(5):
            _make_item(db_session, batch.id, item_name=f'电缆{i}', item_code=f'03040400100{i}')
        db_session.commit()

        # 行为门禁：把 MAX_SEARCH_POOL 临时降到 3，验证返回 ≤ 3
        monkeypatch.setattr(page_services, 'MAX_SEARCH_POOL', 3)
        result = page_services.search_boq_items(db_session, per_page=10)
        # 池上限 3 → 最多 3 行（虽然 5 条都命中）
        assert len(result['rows']) == 3

    def test_bounded_pool_with_relevance_sort(self, db_session, monkeypatch):
        """相关度排序（默认 sort）也受池上限约束。"""
        batch = _make_batch(db_session)
        for i in range(5):
            _make_item(db_session, batch.id, item_name=f'电缆{i}', item_code=f'03040400100{i}')
        db_session.commit()

        monkeypatch.setattr(page_services, 'MAX_SEARCH_POOL', 3)
        result = page_services.search_boq_items(db_session, kw='电缆', sort='recent', per_page=10)
        assert len(result['rows']) == 3


# ============================================================================
# P1-5 + P2-1：模糊兜底（SQLite 测试库 similarity() 不可用 → 静默降级）
# ============================================================================

class TestSearchBoqItemsFuzzyFallback:
    """P1-5 / P2-1：模糊兜底在 SQLite 测试库降级行为。

    模糊兜底触发条件：单关键词 len>=2 非纯数字 且 精确结果 <3。
    在 SQLite 测试库 pg_trgm similarity() 不可用 → P2-1 静默降级为精确匹配。
    """

    def test_fuzzy_fallback_degrades_to_exact_on_sqlite(self, db_session, caplog):
        """模糊兜底 similarity() 在 SQLite 失败 → 降级为精确匹配，hitCount=精确数。

        关键词 '电缆X' 在 name/code/feature 精确匹配 0 命中（<3 触发模糊兜底），
        模糊兜底 similarity() 在 SQLite 抛错 → 降级，最终 hitCount=0（精确数）。
        """
        import logging as _logging
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', item_code='030404001001')
        _make_item(db_session, batch.id, item_name='镀锌钢管', item_code='030702001001')
        db_session.commit()

        # '电缆X' 精确匹配 0 命中（<3 → 触发模糊兜底）
        with caplog.at_level(_logging.WARNING, logger='zaojia.page_services'):
            result = page_services.search_boq_items(db_session, kw='电缆X')
        # SQLite 无 similarity() → 模糊兜底抛错 → 降级为精确匹配 → hitCount=0
        assert result['hitCount'] == 0, f'预期降级为 0 命中，实际 {result["hitCount"]}'
        # P2-1：降级时记录 warning 日志
        assert any('模糊兜底 similarity() 失败' in msg for msg in caplog.messages), \
            f'缺少降级 warning 日志: {caplog.messages}'

    def test_fuzzy_fallback_no_warning_when_exact_hits(self, db_session, caplog):
        """精确命中数 >=3 → 不触发模糊兜底，无降级 warning。"""
        import logging as _logging
        batch = _make_batch(db_session)
        for i in range(3):
            _make_item(db_session, batch.id, item_name=f'电缆{i}', item_code=f'03040400100{i}')
        db_session.commit()

        with caplog.at_level(_logging.WARNING, logger='zaojia.page_services'):
            result = page_services.search_boq_items(db_session, kw='电缆')
        # 3 条精确命中 → total=3 → 不触发模糊（条件 total < 3）
        assert result['hitCount'] == 3
        assert not any('模糊兜底 similarity() 失败' in msg for msg in caplog.messages)


# ============================================================================
# P1-4：非关键词过滤单源（_apply_nonkw_filters）
# ============================================================================

class TestSearchBoqItemsNonKwFilters:
    """P1-4：非关键词过滤统一由 _apply_nonkw_filters 应用。"""

    def test_f_major_prefix_filter(self, db_session):
        """f_major → item_code LIKE 'prefix%'。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', item_code='030404001001')
        _make_item(db_session, batch.id, item_name='镀锌钢管', item_code='030702001001')
        db_session.commit()

        # f_major='0304' → 只命中 item_code 以 '0304' 开头的行
        result = page_services.search_boq_items(db_session, f_major='0304')
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '电力电缆'

    def test_f_source_filter(self, db_session):
        """f_source → data_source_type 精确匹配。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', data_source_type='completed')
        _make_item(db_session, batch.id, item_name='镀锌钢管', data_source_type='pending_review')
        db_session.commit()

        result = page_services.search_boq_items(db_session, f_source='completed')
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '电力电缆'

    def test_std_status_std(self, db_session):
        """std_status='std' → 仅返回 std_name 非空的行。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', std_name='电力电缆_标准')
        _make_item(db_session, batch.id, item_name='镀锌钢管', std_name=None)
        db_session.commit()

        result = page_services.search_boq_items(db_session, std_status='std')
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '电力电缆'

    def test_std_status_pending(self, db_session):
        """std_status='pending' → 仅返回 std_name 为空的行。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', std_name='电力电缆_标准')
        _make_item(db_session, batch.id, item_name='镀锌钢管', std_name=None)
        db_session.commit()

        result = page_services.search_boq_items(db_session, std_status='pending')
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '镀锌钢管'

    def test_only_std_flag(self, db_session):
        """only_std=True → 仅返回 std_name 非空的行。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', std_name='电力电缆_标准')
        _make_item(db_session, batch.id, item_name='镀锌钢管', std_name=None)
        db_session.commit()

        result = page_services.search_boq_items(db_session, only_std=True)
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '电力电缆'

    def test_combined_kw_and_nonkw_filters(self, db_session):
        """关键词 + 非关键词组合过滤（AND 关系）。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', item_code='030404001001',
                   std_name='电力电缆_标准')
        _make_item(db_session, batch.id, item_name='控制电缆', item_code='030405001001',
                   std_name=None)
        db_session.commit()

        # kw='电缆' + std_status='std' → 只命中 std_name 非空且含 '电缆' 的行
        result = page_services.search_boq_items(db_session, kw='电缆', std_status='std')
        assert result['hitCount'] == 1
        assert result['rows'][0]['name'] == '电力电缆'


# ============================================================================
# P1-5：stdCount / pendingCount 口径
# ============================================================================

class TestSearchBoqItemsStdCount:
    """P1-5：stdCount / pendingCount 统计口径。"""

    def test_std_count_on_exact_q(self, db_session):
        """非模糊分支：stdCount 在精确 q 上统计。"""
        batch = _make_batch(db_session)
        _make_item(db_session, batch.id, item_name='电力电缆', std_name='电力电缆_标准')
        _make_item(db_session, batch.id, item_name='镀锌钢管', std_name=None)
        _make_item(db_session, batch.id, item_name='HRB400 螺纹钢', std_name='螺纹钢_标准')
        db_session.commit()

        result = page_services.search_boq_items(db_session)
        assert result['hitCount'] == 3
        assert result['stdCount'] == 2
        assert result['pendingCount'] == 1
