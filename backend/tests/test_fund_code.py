import pytest

from src.utils.fund_code import is_valid_fund_code


@pytest.mark.parametrize(
    "code",
    ["000001", "110011", "159995", "510300", "999999", "000000", "123456"],
)
def test_valid_codes(code):
    assert is_valid_fund_code(code) is True


@pytest.mark.parametrize(
    "code",
    [
        "",            # 空
        "12345",       # 5 位
        "1234567",     # 7 位
        "abc123",      # 含字母
        "sh000001",    # 带前缀
        "00001a",      # 末位字母
        " 000001",     # 前导空格
        "000001 ",     # 尾随空格
        "00.001",      # 点
        "TODO",        # placeholder
    ],
)
def test_invalid_codes(code):
    assert is_valid_fund_code(code) is False


def test_non_str_input():
    assert is_valid_fund_code(None) is False
    assert is_valid_fund_code(123456) is False
    assert is_valid_fund_code(["000001"]) is False
