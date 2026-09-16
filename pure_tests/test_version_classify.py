"""版本识别纯函数测试"""
import pytest
from data.version_lookup import classify_version, classify_version_full, cross_validate, _load_lookup


class TestLayer1UniqueCode:
    """第1层：独有编码直接定版本"""

    def test_2013_unique_code(self):
        """030408 前缀指向 2013 → 2013"""
        result = classify_version("030408001001", "电力电缆")
        assert result["version"] == "2013"
        assert result["layer"] in (1, 4)

    def test_2024_unique_code(self):
        """031001 前缀指向 2024 → 2024"""
        result = classify_version("031001001001", "管道")
        assert result["version"] == "2024"
        assert result["layer"] in (1, 4)

    def test_2013_unique_code_no_name(self):
        """独有编码不需要名称也能定"""
        result = classify_version("010515001001", "")
        assert result["version"] == "2013"
        assert result["confidence"] == "high"


class TestLayer4PrefixFallback:
    """第4层：前6位前缀倾向"""

    def test_030408_prefix_2013(self):
        """030408 前缀指向 2013 → 2013, low"""
        result = classify_version("030408999001", "其他电缆")
        assert result["version"] == "2013"
        assert result["confidence"] == "low"

    def test_031001_prefix_2024(self):
        """031001 前缀指向 2024 → 2024, low"""
        result = classify_version("031001999001", "其他管道")
        assert result["version"] == "2024"
        assert result["confidence"] == "low"


class TestEdgeCases:
    """边界情况"""

    def test_empty_code(self):
        """空编码 → unknown"""
        result = classify_version("", "")
        assert result["version"] == "unknown"
        assert result["confidence"] == "unknown"

    def test_short_code(self):
        """太短的编码 → unknown"""
        result = classify_version("123", "")
        assert result["version"] == "unknown"
        assert result["confidence"] == "unknown"

    def test_none_name(self):
        """None 名称不报错"""
        result = classify_version("030408001001", None)
        assert result["version"] == "2013"  # 独有编码不受名称影响


class TestCrossValidate:
    """两次校验"""

    def test_layer1_no_cross_validate(self):
        """第1层不需要交叉校验"""
        result = {"version": "2013", "confidence": "high", "layer": 1}
        validated = cross_validate("030408001001", "电力电缆", result)
        assert validated == result

    def test_consistent_keep(self):
        """两次一致 → 保持"""
        result = {"version": "2013", "confidence": "medium", "layer": 3}
        validated = cross_validate("030408001001", "电力电缆测试", result)
        assert validated["version"] == "2013"

    def test_high_plus_unknown_keep_high(self):
        """high + unknown → 保持 high"""
        result = {"version": "2024", "confidence": "high", "layer": 2}
        validated = cross_validate("030412003001", "桥架", result)
        # 030412 前缀不在独有前缀里，cross=unknown
        assert validated["confidence"] == "high"


class TestFullClassification:
    """完整识别流程"""

    def test_full_2013_unique(self):
        result = classify_version_full("030408001001", "电力电缆")
        assert result["version"] == "2013"

    def test_full_2024_unique(self):
        result = classify_version_full("031001001001", "管道")
        assert result["version"] == "2024"

    def test_full_unknown(self):
        result = classify_version_full("999999999999", "未知")
        assert result["version"] == "unknown"


class TestLookupData:
    """查表数据完整性"""

    def test_lookup_loaded(self):
        lookup = _load_lookup()
        assert len(lookup["only_2013"]) > 500
        assert len(lookup["only_2024"]) > 500
        assert len(lookup["both"]) > 1000

    def test_known_codes_in_lookup(self):
        lookup = _load_lookup()
        # 030408 应该在 2013 里
        assert "030408001" in lookup["codes_2013"] or "030408001" in lookup["only_2013"]
