"""material_classifier v3 前缀初筛测试"""
import pytest
from app.services.material_classifier import (
    classify_boq,
    _classify_by_prefix,
    PREFIX_WHITELIST_2013,
    PREFIX_WHITELIST_2024,
)


class TestPrefixWhitelist:
    """前缀白名单表完整性"""

    def test_2013_has_cable(self):
        assert "030408" in PREFIX_WHITELIST_2013
        assert PREFIX_WHITELIST_2013["030408"]["category"] == "电线电缆"

    def test_2024_has_cable(self):
        assert "030409" in PREFIX_WHITELIST_2024
        assert PREFIX_WHITELIST_2024["030409"]["category"] == "电线电缆"

    def test_2024_has_pipe(self):
        assert "031001" in PREFIX_WHITELIST_2024
        assert PREFIX_WHITELIST_2024["031001"]["category"] == "管道"

    def test_2013_has_rebar(self):
        assert "010515" in PREFIX_WHITELIST_2013
        assert PREFIX_WHITELIST_2013["010515"]["category"] == "钢筋"

    def test_2024_has_rebar(self):
        assert "010506" in PREFIX_WHITELIST_2024
        assert PREFIX_WHITELIST_2024["010506"]["category"] == "钢筋"


class TestClassifyByPrefix:
    """前缀初筛函数"""

    def test_2013_cable(self):
        result = _classify_by_prefix("030408001001", "2013", "电力电缆", "YJV-5*10")
        assert result is not None
        assert result.category == "电线电缆"

    def test_2024_cable(self):
        result = _classify_by_prefix("030409001001", "2024", "电力电缆", "YJV-5*10")
        assert result is not None
        assert result.category == "电线电缆"

    def test_2013_cable_head_excluded(self):
        """030408006 终端头 → 排除"""
        result = _classify_by_prefix("030408006001", "2013", "电缆终端头", "")
        assert result is None

    def test_2024_cable_head_excluded(self):
        """030409003 电力电缆头 → 排除"""
        result = _classify_by_prefix("030409003001", "2024", "电力电缆头", "")
        assert result is None

    def test_unknown_prefix_returns_none(self):
        result = _classify_by_prefix("999999001001", "2013", "未知", "")
        assert result is None

    def test_empty_code_returns_none(self):
        result = _classify_by_prefix("", "2013", "电力电缆", "")
        assert result is None


class TestClassifyBoqV3:
    """v3 主入口：前缀 + 版本"""

    def test_cable_with_code(self):
        """传编码+版本 → 前缀初筛"""
        result = classify_boq("电力电缆", "YJV-5*10", "030408001001", "2013")
        assert result.category == "电线电缆"

    def test_cable_without_code(self):
        """不传编码 → 纯文本兜底"""
        result = classify_boq("电力电缆", "YJV-5*10")
        assert result.category == "电线电缆"

    def test_rebar_with_code(self):
        result = classify_boq("现浇构件钢筋", "HRB400 Φ20", "010515001001", "2013")
        assert result.category == "钢筋"

    def test_conduit_sc25(self):
        """SC25 → 配管配线"""
        result = classify_boq("配管", "SC25*3.25", "030412001001", "2013")
        assert result.category == "配管配线"

    def test_tray_excluded(self):
        """桥架排除"""
        result = classify_boq("槽式电缆桥架", "200*100", "030412003001", "2013")
        assert result.category != "电线电缆"


class TestBackwardCompatibility:
    """向后兼容：不传编码时行为不变"""

    def test_no_code_no_version(self):
        result = classify_boq("YJV电缆", "YJV-5*10")
        assert result.category == "电线电缆"

    def test_cement_no_prefix(self):
        """水泥走纯文本兜底（无前表白名单）"""
        result = classify_boq("普通硅酸盐水泥", "P.O 42.5")
        assert result.category == "水泥"
