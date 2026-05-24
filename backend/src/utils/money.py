"""金额 / 净值 / 份额 / 百分比的整数转换。

R1: 严禁 float / Decimal 存储任何金额。所有 DB 字段都是 int(用对应 SCALE 缩放)。
本模块提供 5 个域的双向转换函数(共 10 个函数):

| 域           | scale  | DB 字段后缀         | 例                                  |
|--------------|--------|---------------------|-------------------------------------|
| 净值         | 10000  | _x10000             | 1.2345          → 12345             |
| 元 → 分      | 100    | _x100               | 12.34 元        → 1234              |
| 万元(精度到元)| 10000  | _wan_x10000         | 1.2345 万元     → 12345             |
| 份额         | 100    | _x100               | 100.50 份       → 10050             |
| 百分比/涨跌幅 | 10000  | _x10000             | 0.0123 (=1.23%) → 123 (bps)         |

约定:
- to_int 函数接收 str | int | float | Decimal,返回 int(银行家舍入到最近整数)
- from_int 函数接收 int,返回 Decimal(避免再陷入 float 坑)
- 严禁在调用方再做 float 运算后转 int,所有缩放走本模块
"""

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Union

Number = Union[str, int, float, Decimal]

NAV_SCALE: int = 10_000
YUAN_SCALE: int = 100
WAN_YUAN_SCALE: int = 10_000
SHARE_SCALE: int = 100
PCT_SCALE: int = 10_000


def _to_int(value: Number, scale: int) -> int:
    if value is None:
        raise ValueError("money conversion received None")
    # 走 str 通道,避免 float 二进制精度直接进入 Decimal
    d = Decimal(str(value)) * Decimal(scale)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def _from_int(int_value: int, scale: int) -> Decimal:
    return Decimal(int_value) / Decimal(scale)


# ===== 净值 =====
def nav_to_int(nav: Number) -> int:
    return _to_int(nav, NAV_SCALE)


def int_to_nav(nav_int: int) -> Decimal:
    return _from_int(nav_int, NAV_SCALE)


# ===== 元 → 分 =====
def yuan_to_int(yuan: Number) -> int:
    return _to_int(yuan, YUAN_SCALE)


def int_to_yuan(fen: int) -> Decimal:
    return _from_int(fen, YUAN_SCALE)


# ===== 万元(× 10000 精度到元) =====
def wan_yuan_to_int(wan_yuan: Number) -> int:
    return _to_int(wan_yuan, WAN_YUAN_SCALE)


def int_to_wan_yuan(wan_yuan_int: int) -> Decimal:
    return _from_int(wan_yuan_int, WAN_YUAN_SCALE)


# ===== 份额 =====
def shares_to_int(shares: Number) -> int:
    return _to_int(shares, SHARE_SCALE)


def int_to_shares(shares_int: int) -> Decimal:
    return _from_int(shares_int, SHARE_SCALE)


# ===== 百分比 / 涨跌幅(0.0123 = 1.23%)=====
def pct_to_int(pct: Number) -> int:
    return _to_int(pct, PCT_SCALE)


def int_to_pct(pct_int: int) -> Decimal:
    return _from_int(pct_int, PCT_SCALE)
