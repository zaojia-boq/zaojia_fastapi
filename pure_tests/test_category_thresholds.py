"""M7 任务1.5：按大类配置异常阈值测试"""
import pytest
from data.price_calc import (
    DEFAULT_THRESHOLD,
    CATEGORY_THRESHOLDS,
    get_threshold_for_category,
    compute_kpis,
)


class TestCategoryThresholds:
    """大类阈值配置"""

    def test_cable_threshold_is_90(self):
        """电线电缆阈值 0.90（铜价波动大放宽）"""
        assert get_threshold_for_category("电线电缆") == 0.90

    def test_rebar_threshold_is_50(self):
        assert get_threshold_for_category("钢筋") == 0.50

    def test_cement_threshold_is_30(self):
        assert get_threshold_for_category("水泥") == 0.30

    def test_concrete_threshold_is_30(self):
        assert get_threshold_for_category("混凝土") == 0.30

    def test_default_threshold(self):
        """未匹配的大类用 _default"""
        assert get_threshold_for_category("未知大类") == 0.30
        assert get_threshold_for_category("") == 0.30

    def test_all_categories_have_threshold(self):
        """CATEGORY_THRESHOLDS 包含 _default"""
        assert "_default" in CATEGORY_THRESHOLDS


class TestComputeKpisWithCategory:
    """compute_kpis 按大类阈值判定异常"""

    def test_cable_loose_threshold(self):
        """电线电缆阈值 0.90：偏离 90% 以上才算异常"""
        rows = [
            {"unit_rate_num": 100, "quantity_num": 10},
            {"unit_rate_num": 100, "quantity_num": 10},
            {"unit_rate_num": 350, "quantity_num": 10},  # 均价183.3，偏离90.9% > 90%
        ]
        result = compute_kpis(rows, category="电线电缆")
        # 只有 350 偏离 > 90%
        assert result["anomaly_count"] == 1

    def test_cement_tight_threshold(self):
        """水泥阈值 0.30：偏离 50% 算异常"""
        rows = [
            {"unit_rate_num": 100, "quantity_num": 10},
            {"unit_rate_num": 150, "quantity_num": 10},  # 偏离 50% > 30%
            {"unit_rate_num": 200, "quantity_num": 10},  # 偏离 100% > 30%
        ]
        result = compute_kpis(rows, category="水泥")
        # 两个都异常
        assert result["anomaly_count"] == 2

    def test_no_category_uses_default(self):
        """不传 category 用默认阈值 0.30"""
        rows = [
            {"unit_rate_num": 100, "quantity_num": 10},
            {"unit_rate_num": 150, "quantity_num": 10},
        ]
        result = compute_kpis(rows)
        assert result["threshold"] == DEFAULT_THRESHOLD

    def test_result_contains_threshold(self):
        """返回值包含 threshold 字段"""
        rows = [{"unit_rate_num": 100, "quantity_num": 10}]
        result = compute_kpis(rows, category="钢筋")
        assert "threshold" in result
        assert result["threshold"] == 0.50
