"""utils/money.py 测试 — 重点验证 R1 整数转换无浮点精度泄漏。"""

from decimal import Decimal

import pytest

from src.utils.money import (
    NAV_SCALE,
    PCT_SCALE,
    SHARE_SCALE,
    WAN_YUAN_SCALE,
    YUAN_SCALE,
    int_to_nav,
    int_to_pct,
    int_to_shares,
    int_to_wan_yuan,
    int_to_yuan,
    nav_to_int,
    pct_to_int,
    shares_to_int,
    wan_yuan_to_int,
    yuan_to_int,
)

# ============ 常量自检 ============


def test_scales_match_spec():
    assert NAV_SCALE == 10_000
    assert YUAN_SCALE == 100
    assert WAN_YUAN_SCALE == 10_000
    assert SHARE_SCALE == 100
    assert PCT_SCALE == 10_000


# ============ 净值(× 10000) ============


@pytest.mark.parametrize(
    "nav, expected",
    [
        ("1.2345", 12345),
        ("1.0000", 10000),
        ("0.9999", 9999),
        ("3.1416", 31416),
        (1, 10000),
        (0, 0),
        ("-1.2345", -12345),
    ],
)
def test_nav_to_int_basic(nav, expected):
    assert nav_to_int(nav) == expected


def test_nav_round_trip():
    assert int_to_nav(12345) == Decimal("1.2345")
    assert int_to_nav(0) == Decimal("0")


def test_nav_to_int_accepts_decimal_directly():
    assert nav_to_int(Decimal("1.2345")) == 12345


def test_nav_to_int_handles_str_to_avoid_float_trap():
    # 0.1 + 0.2 = 0.30000000000000004 in float;str(...) 转入 Decimal 后仍精确处理
    assert nav_to_int("0.0003") == 3


def test_nav_banker_rounding_half_even():
    # 0.5 → 偶数 0;1.5 → 偶数 2;2.5 → 偶数 2
    assert nav_to_int("0.00005") == 0   # 0.5 → 0
    assert nav_to_int("0.00015") == 2   # 1.5 → 2
    assert nav_to_int("0.00025") == 2   # 2.5 → 2


# ============ 元 → 分(× 100) ============


def test_yuan_to_int_basic():
    assert yuan_to_int("12.34") == 1234
    assert yuan_to_int("0.01") == 1
    assert yuan_to_int("0") == 0


def test_yuan_to_int_large_amount():
    # 12.3 亿 = 1_230_000_000.99 元 → 123_000_000_099 分
    assert yuan_to_int("1234567890.99") == 123_456_789_099


def test_yuan_to_int_negative():
    assert yuan_to_int("-12.34") == -1234


def test_yuan_round_trip():
    assert int_to_yuan(1234) == Decimal("12.34")
    assert int_to_yuan(0) == Decimal("0")


# ============ 万元(× 10000,精度到元) ============


def test_wan_yuan_to_int_basic():
    # 1.2345 万元 = 12345 元 → 存 12345
    assert wan_yuan_to_int("1.2345") == 12345


def test_wan_yuan_to_int_main_inflow_5_yi():
    # 主力净流入 5 亿元 = 50000 万元 → 50000 × 10000 = 500_000_000
    assert wan_yuan_to_int("50000") == 500_000_000


def test_wan_yuan_to_int_negative_outflow():
    assert wan_yuan_to_int("-1234.5678") == -12_345_678


def test_wan_yuan_round_trip():
    assert int_to_wan_yuan(12345) == Decimal("1.2345")


# ============ 份额(× 100) ============


def test_shares_to_int_basic():
    assert shares_to_int("100.50") == 10050
    assert shares_to_int("0.01") == 1
    assert shares_to_int("0") == 0


def test_shares_round_trip():
    # 注意:Decimal(10050) / Decimal(100) = Decimal('100.5'),不是 '100.50'
    assert int_to_shares(10050) == Decimal("100.5")


# ============ 百分比 / 涨跌幅(× 10000,1.23% = 123) ============


def test_pct_to_int_basic():
    assert pct_to_int("0.0123") == 123   # 1.23%
    assert pct_to_int("0.10") == 1000    # 涨停 10%
    assert pct_to_int("-0.10") == -1000  # 跌停 -10%
    assert pct_to_int("0") == 0


def test_pct_round_trip():
    assert int_to_pct(123) == Decimal("0.0123")


# ============ 异常 ============


def test_none_raises():
    with pytest.raises(ValueError):
        nav_to_int(None)
    with pytest.raises(ValueError):
        yuan_to_int(None)
    with pytest.raises(ValueError):
        wan_yuan_to_int(None)
    with pytest.raises(ValueError):
        shares_to_int(None)
    with pytest.raises(ValueError):
        pct_to_int(None)
