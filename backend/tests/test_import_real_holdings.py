"""import_real_holdings 单测 — 验证三桶逻辑 + R1 整数换算。

覆盖:
- 转换规则:用户给的样例(2.2873 → 22873;45898.27 → 4589827)
- updated:holdings 表里有 + REAL_HOLDINGS 里有 → UPDATE
- zeroed: holdings 表里有 + REAL_HOLDINGS 里没有 → cost=0/shares=0
- unmatched:REAL_HOLDINGS 里有 + holdings 表里没有 → 跳过不动表
- 幂等:跑两次结果一致
"""

from datetime import date
from unittest.mock import patch

import pytest

from scripts import import_real_holdings as mod
from src.models import Fund, Holding
from src.utils.money import nav_to_int, shares_to_int


# =====================================================================
# 转换规则:用户给的样例(任务描述里写死的 verify 点)
# =====================================================================


def test_nav_to_int_user_sample():
    """user spec:cost_nav=2.2873 → cost_nav_x10000=22873。"""
    assert nav_to_int("2.2873") == 22873


def test_shares_to_int_user_sample():
    """user spec:shares=45898.27 → shares_x100=4589827。"""
    assert shares_to_int("45898.27") == 4589827


# =====================================================================
# 三桶逻辑测试 — patch REAL_HOLDINGS 用小数据
# =====================================================================


def _seed_fund(session, code: str) -> None:
    session.add(Fund(fund_code=code, fund_name=f"基金{code}", fund_type="混合型"))


def _seed_holding(session, code: str, cost_nav_x10000: int = 10000, shares_x100: int = 1_000_000) -> None:
    session.add(
        Holding(
            fund_code=code,
            cost_nav_x10000=cost_nav_x10000,
            shares_x100=shares_x100,
            bought_at=date(2025, 1, 1),
            note="placeholder",
        )
    )


@pytest.fixture
def fake_real_holdings():
    """3 条假数据,patch REAL_HOLDINGS。"""
    return [
        {"fund_code": "100001", "cost_nav": "2.2873", "shares": "45898.27"},
        {"fund_code": "100002", "cost_nav": "1.5000", "shares": "1000.00"},
        {"fund_code": "100099", "cost_nav": "9.9999", "shares": "0.01"},  # 这条在 holdings 表不存在
    ]


def test_run_updates_existing_holdings(db_session, fake_real_holdings):
    # holdings 表里 100001 + 100002 + 100003(后者要被归零)
    for c in ("100001", "100002", "100003"):
        _seed_fund(db_session, c)
        _seed_holding(db_session, c)
    db_session.commit()

    with patch.object(mod, "REAL_HOLDINGS", fake_real_holdings):
        stats = mod.run(db_session)

    assert set(stats["updated"]) == {"100001", "100002"}

    # 100001:验证用户样例换算落库
    h1 = db_session.query(Holding).filter_by(fund_code="100001").one()
    assert h1.cost_nav_x10000 == 22873
    assert h1.shares_x100 == 4_589_827

    # 100002:1.5000 → 15000,1000.00 → 100000
    h2 = db_session.query(Holding).filter_by(fund_code="100002").one()
    assert h2.cost_nav_x10000 == 15000
    assert h2.shares_x100 == 100_000


def test_run_zeroes_holdings_without_pdf_data(db_session, fake_real_holdings):
    # 只有 100003 在 holdings 表,但不在 REAL_HOLDINGS → 应归零
    _seed_fund(db_session, "100003")
    _seed_holding(db_session, "100003", cost_nav_x10000=12345, shares_x100=999_999)
    db_session.commit()

    with patch.object(mod, "REAL_HOLDINGS", fake_real_holdings):
        stats = mod.run(db_session)

    assert stats["zeroed"] == ["100003"]

    h = db_session.query(Holding).filter_by(fund_code="100003").one()
    assert h.cost_nav_x10000 == 0
    assert h.shares_x100 == 0
    # bought_at / note 应保留(只动金额字段)
    assert h.bought_at == date(2025, 1, 1)
    assert h.note == "placeholder"


def test_run_warns_unmatched_codes(db_session, fake_real_holdings):
    """REAL_HOLDINGS 里有 100099,但 holdings 表里没有 → 进 unmatched,不创建新行。"""
    _seed_fund(db_session, "100001")
    _seed_holding(db_session, "100001")
    db_session.commit()

    with patch.object(mod, "REAL_HOLDINGS", fake_real_holdings):
        stats = mod.run(db_session)

    assert "100099" in stats["unmatched"]
    # 不应该 INSERT 100099 进 holdings
    assert db_session.query(Holding).filter_by(fund_code="100099").first() is None


def test_run_is_idempotent(db_session, fake_real_holdings):
    """跑两次,结果完全一致(updated/zeroed 都是同一批 code)。"""
    for c in ("100001", "100002", "100003"):
        _seed_fund(db_session, c)
        _seed_holding(db_session, c)
    db_session.commit()

    with patch.object(mod, "REAL_HOLDINGS", fake_real_holdings):
        stats1 = mod.run(db_session)
        stats2 = mod.run(db_session)

    assert sorted(stats1["updated"]) == sorted(stats2["updated"])
    assert sorted(stats1["zeroed"]) == sorted(stats2["zeroed"])
    assert sorted(stats1["unmatched"]) == sorted(stats2["unmatched"])

    # 第二次跑完落库值也应该和第一次一致
    h1 = db_session.query(Holding).filter_by(fund_code="100001").one()
    assert h1.cost_nav_x10000 == 22873
    assert h1.shares_x100 == 4_589_827


# =====================================================================
# REAL_HOLDINGS 自检 — 防 OCR 录入低级错(重复 / 格式)
# =====================================================================


def test_real_holdings_has_42_entries():
    assert len(mod.REAL_HOLDINGS) == 42


def test_real_holdings_codes_are_unique():
    codes = [h["fund_code"] for h in mod.REAL_HOLDINGS]
    assert len(set(codes)) == len(codes), f"重复 code: {set([c for c in codes if codes.count(c) > 1])}"


def test_real_holdings_codes_are_6_digit_strings():
    for h in mod.REAL_HOLDINGS:
        c = h["fund_code"]
        assert isinstance(c, str) and len(c) == 6 and c.isdigit(), f"bad code: {c!r}"


def test_real_holdings_values_are_positive_strings():
    for h in mod.REAL_HOLDINGS:
        assert isinstance(h["cost_nav"], str)
        assert isinstance(h["shares"], str)
        assert nav_to_int(h["cost_nav"]) > 0, f"{h['fund_code']} cost_nav 非正"
        assert shares_to_int(h["shares"]) > 0, f"{h['fund_code']} shares 非正"
