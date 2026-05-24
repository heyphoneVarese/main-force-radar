"""基金代码校验。

A 股开放式基金 / ETF / 联接基金均为 6 位纯数字代码(如 110011 易方达消费行业)。
不带交易所前缀(sh/sz 前缀仅用于 secid 拼接,akshare 不同源各有格式)。
"""

import re

_FUND_CODE_RE = re.compile(r"^\d{6}$")


def is_valid_fund_code(code: object) -> bool:
    """6 位纯数字 str → True;其他(非 str / 空 / 长度不对 / 非数字)→ False。"""
    if not isinstance(code, str):
        return False
    return bool(_FUND_CODE_RE.match(code))
