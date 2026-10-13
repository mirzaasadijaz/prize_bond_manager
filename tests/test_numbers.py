import pytest

from app.processing.numbers import NumberError, normalize_number, parse_pattern


def test_normalize_pads_and_keys():
    assert normalize_number("123") == ("000123", 123)
    assert normalize_number(" 000123 ") == ("000123", 123)
    assert normalize_number(123456.0) == ("123456", 123456)
    assert normalize_number("123456.0") == ("123456", 123456)


@pytest.mark.parametrize("bad", ["", None, "12a", "-5", 1.5, "1 2", "١٢"])
def test_normalize_rejects(bad):
    with pytest.raises(NumberError):
        normalize_number(bad)


def test_pattern_mixes_ranges_lists_and_keeps_order():
    result = parse_pattern("100001-100003, 777, 500 to 502")
    assert [n for n, _ in result.numbers] == [
        "100001", "100002", "100003", "000777", "000500", "000501", "000502"]
    assert result.ok


def test_pattern_step_and_descending():
    assert [k for _, k in parse_pattern("10-20:5").numbers] == [10, 15, 20]
    assert [k for _, k in parse_pattern("105-101").numbers] == [105, 104, 103, 102, 101]


def test_pattern_reports_duplicates_and_errors():
    result = parse_pattern("1-3, 2, x9")
    assert [k for _, k in result.numbers] == [1, 2, 3]
    assert result.duplicates == ["000002"]
    assert result.errors and not result.ok
    assert "duplicate" in result.problems()


def test_pattern_range_limit():
    assert "too large" in parse_pattern("1-999999").errors[0]


def test_lenient_ignores_prose_and_short_numbers():
    result = parse_pattern("Page 3 of 9: 123456 and 234567-234569, ref 12", lenient=True)
    assert [k for _, k in result.numbers] == [123456, 234567, 234568, 234569]
    assert result.errors == []
