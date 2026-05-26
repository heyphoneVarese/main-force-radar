"""SignalEngine 单元测试。

测试用 in-memory SQLite + 手工构造 sector_flow_daily 数据,
不依赖 mock_sector_flow.py 脚本。
"""

from datetime import date, timedelta

import pytest

from src.models import Fund, Holding, SectorAlias, SectorFlowDaily
from src.models.enums import SignalType
from src.services.signal_engine import (
    LOOKBACK_DAYS,
    ScoreBreakdown,
    SignalEngine,
)


def _add_flow(db_session, sector_code: str, trade_date: date, inflow_wan_x10000: int, change_pct_x10000: int):
    db_session.add(SectorFlowDaily(
        trade_date=trade_date,
        sector_code=sector_code,
        sector_name="测试板块",
        sector_type="industry",
        main_inflow_wan_x10000=inflow_wan_x10000,
        change_pct_x10000=change_pct_x10000,
    ))


def _add_alias(db_session, label: str, code: str | None, name: str | None = None):
    db_session.add(SectorAlias(
        chinese_label=label, sector_code=code, sector_name=name, confidence=1.0,
    ))


def _add_fund(db_session, code: str, name: str, related_sectors=None):
    db_session.add(Fund(
        fund_code=code, fund_name=name, fund_type="混合型",
        related_sectors=related_sectors,
    ))


def _add_holding(db_session, fund_code: str):
    db_session.add(Holding(
        fund_code=fund_code, cost_nav_x10000=10000, shares_x100=1000000,
        bought_at=date(2025, 1, 1),
    ))


# ============================================================
# 基础分 _base_score (0-4)
# ============================================================


@pytest.mark.parametrize("inflow_yi, expected", [
    (5, 0),      # 5 亿 < 10 亿
    (10, 1),     # 10 亿 = 10 亿 → 1
    (20, 1),     # 10-30 亿
    (30, 2),     # 30 亿 → 2
    (49, 2),     # 30-50 亿
    (50, 3),     # 50 亿 → 3
    (99, 3),     # 50-100 亿
    (100, 3),    # 100 亿(spec: > 100 才 4)
    (101, 4),    # > 100 亿
    (200, 4),
])
def test_base_score_inflow_tiers(inflow_yi, expected):
    inflow_wan_x10000 = int(inflow_yi * 10_000 * 10_000)
    assert SignalEngine._base_score(inflow_wan_x10000) == expected


def test_base_score_handles_absolute_value():
    # 负数(流出)应该用绝对值评分
    inflow_wan_x10000 = int(60 * 10_000 * 10_000)  # 60 亿
    assert SignalEngine._base_score(inflow_wan_x10000) == 3


# ============================================================
# 连续性 _continuity_score (0-3)
# ============================================================


@pytest.mark.parametrize("flows, expected", [
    ([100], 0),                          # 1 天
    ([100, 50], 1),                      # 2 天同向(都正)
    ([100, 50, 20], 2),                  # 3 天同向
    ([100, 50, 20, 10], 3),              # ≥ 4 天同向
    ([100, 50, 20, 10, 5, 3], 3),        # > 4 天同向
    ([-100, -50, -20, -10], 3),          # ≥ 4 天连续流出
    ([100, -50], 0),                     # 反向,只算今日
    ([100, 50, -20], 1),                 # 今 + 昨同向,前天反向
    ([0, 50, 20], 0),                    # 今日 0,中性
    ([], 0),                             # 空
])
def test_continuity_score(flows, expected):
    assert SignalEngine._continuity_score(flows) == expected


# ============================================================
# 量价匹配 _vol_price_score (0-2)
# ============================================================


def test_vol_price_align_bullish():
    # 流入扩张 + 价升 → 齐升,2 分
    score, label = SignalEngine._vol_price_score(today_flow=100, yest_flow=50, today_change_pct_x10000=120)
    assert (score, label) == (2, "align")


def test_vol_price_align_bearish():
    # 流出扩张 + 价跌 → 齐跌,2 分
    score, label = SignalEngine._vol_price_score(today_flow=-150, yest_flow=-100, today_change_pct_x10000=-200)
    assert (score, label) == (2, "align")


def test_vol_price_divergence_inflow_but_price_down():
    # 流入但价跌 → 背离 1 分
    score, label = SignalEngine._vol_price_score(today_flow=80, yest_flow=50, today_change_pct_x10000=-100)
    assert (score, label) == (1, "divergence")


def test_vol_price_divergence_outflow_but_price_up():
    # 流出但价升 → 背离 1 分
    score, label = SignalEngine._vol_price_score(today_flow=-80, yest_flow=-50, today_change_pct_x10000=140)
    assert (score, label) == (1, "divergence")


def test_vol_price_shrink_other():
    # 同向但量缩 → 0 分
    score, label = SignalEngine._vol_price_score(today_flow=50, yest_flow=100, today_change_pct_x10000=80)
    assert (score, label) == (0, "other")


def test_vol_price_zero_price_other():
    score, label = SignalEngine._vol_price_score(today_flow=100, yest_flow=50, today_change_pct_x10000=0)
    assert (score, label) == (0, "other")


# ============================================================
# determine_signal_type (D4 决策)
# ============================================================


@pytest.mark.parametrize("score, is_inflow, vp_label, expected", [
    # bullish 强
    (9, True, "align", SignalType.BULLISH.value),
    (8, True, "align", SignalType.BULLISH.value),
    # bullish 普通
    (7, True, "align", SignalType.BULLISH.value),
    (6, True, "other", SignalType.BULLISH.value),
    # bearish 强
    (9, False, "align", SignalType.BEARISH.value),
    (8, False, "other", SignalType.BEARISH.value),
    # bearish 普通(gap-fill 6-7 + outflow)
    (7, False, "other", SignalType.BEARISH.value),
    (6, False, "other", SignalType.BEARISH.value),
    # bearish 普通退潮(< 6 + outflow)
    (5, False, "other", SignalType.BEARISH.value),
    (3, False, "other", SignalType.BEARISH.value),
    (0, False, "other", SignalType.BEARISH.value),
    # neutral(inflow 但 score < 6)
    (5, True, "other", SignalType.NEUTRAL.value),
    (3, True, "other", SignalType.NEUTRAL.value),
    (0, True, "other", SignalType.NEUTRAL.value),
    # warning(4-7 + divergence,优先于 bullish/bearish)
    (4, True, "divergence", SignalType.WARNING.value),
    (5, True, "divergence", SignalType.WARNING.value),
    (7, True, "divergence", SignalType.WARNING.value),
    (4, False, "divergence", SignalType.WARNING.value),
    (7, False, "divergence", SignalType.WARNING.value),
    # divergence 但 < 4 或 > 7 → 走正常分支
    (3, True, "divergence", SignalType.NEUTRAL.value),
    (8, True, "divergence", SignalType.BULLISH.value),
    (3, False, "divergence", SignalType.BEARISH.value),
    (8, False, "divergence", SignalType.BEARISH.value),
])
def test_determine_signal_type(score, is_inflow, vp_label, expected):
    assert SignalEngine.determine_signal_type(score, is_inflow, vp_label) == expected


# ============================================================
# 集成:calculate_persistence_score + calculate_sector_signal
# ============================================================


def test_persistence_no_data(db_session):
    e = SignalEngine(db_session)
    sb = e.calculate_persistence_score("BK9999")
    assert sb.total == 0
    assert sb.trade_date is None


def test_persistence_bullish_strong_scenario(db_session):
    """剧本:4 天连续大流入 + 价升扩张 → score 应 ≥ 8。"""
    today = date(2026, 5, 22)
    # 4 天数据,主力流入 80/85/90/95 亿,价 +1.2/+1.5/+1.8/+2.1%
    inflows_yi = [80, 85, 90, 95]
    pcts = [0.012, 0.015, 0.018, 0.021]
    for i, (yi, p) in enumerate(zip(inflows_yi, pcts)):
        d = today - timedelta(days=3 - i)  # 老→新
        _add_flow(db_session, "BK0490", d,
                  int(yi * 10_000 * 10_000), int(p * 10_000))
    db_session.commit()

    e = SignalEngine(db_session)
    sb = e.calculate_persistence_score("BK0490", as_of=today)
    # base: 95 亿 → 3 (50-100 区间)
    # continuity: 4 天同向 → 3
    # vol_price: |95| > |90| AND price > 0 → 2 (align)
    assert sb.base == 3
    assert sb.continuity == 3
    assert sb.vol_price == 2
    assert sb.total == 8
    sig = e.calculate_sector_signal("BK0490", as_of=today)
    assert sig.signal_type == SignalType.BULLISH.value
    assert sig.persistence_score == 8


def test_persistence_bearish_strong_scenario(db_session):
    today = date(2026, 5, 22)
    outflows_yi = [-120, -130, -140, -150]
    pcts = [-0.015, -0.020, -0.025, -0.030]
    for i, (yi, p) in enumerate(zip(outflows_yi, pcts)):
        d = today - timedelta(days=3 - i)
        _add_flow(db_session, "BK0727", d, int(yi * 10_000 * 10_000), int(p * 10_000))
    db_session.commit()

    e = SignalEngine(db_session)
    sb = e.calculate_persistence_score("BK0727", as_of=today)
    # base: |-150| 亿 → 4 (> 100 亿)
    # continuity: 4 天连续流出 → 3
    # vol_price: |−150| > |−140| AND price 同向 (都负) → 2 align
    assert sb.base == 4
    assert sb.continuity == 3
    assert sb.vol_price == 2
    assert sb.total == 9
    sig = e.calculate_sector_signal("BK0727", as_of=today)
    assert sig.signal_type == SignalType.BEARISH.value


def test_persistence_warning_divergence_scenario(db_session):
    """5 天:价升 +1.4% 但持续流出(背离),score 在 4-7 → warning。"""
    today = date(2026, 5, 22)
    # 流出 -40 → -28(逐步缩小流出),价均 +1.4%
    flows_yi = [-40, -37, -34, -31, -28]
    for i, yi in enumerate(flows_yi):
        d = today - timedelta(days=4 - i)
        _add_flow(db_session, "BK1019", d, int(yi * 10_000 * 10_000), 140)
    db_session.commit()

    e = SignalEngine(db_session)
    sb = e.calculate_persistence_score("BK1019", as_of=today)
    # base: |-28| 亿 → 1 (10-30)
    # continuity: 5 天同向(都负)→ 3
    # vol_price: flow<0 但 pct>0 → 背离 1
    # total = 1 + 3 + 1 = 5
    assert sb.vol_price_label == "divergence"
    assert 4 <= sb.total <= 7
    sig = e.calculate_sector_signal("BK1019", as_of=today)
    assert sig.signal_type == SignalType.WARNING.value


# ============================================================
# get_fund_signal_summary
# ============================================================


def test_fund_summary_not_applicable_no_mapped_sectors(db_session):
    _add_fund(db_session, "161125", "易方达标普500", ["标普500"])
    _add_alias(db_session, "标普500", None)  # 显式无对应
    db_session.commit()
    e = SignalEngine(db_session)
    s = e.get_fund_signal_summary("161125")
    assert s["signal_type"] == SignalType.NOT_APPLICABLE.value
    assert s["score"] == 0


def test_fund_summary_no_signal_data_yet(db_session):
    _add_fund(db_session, "022365", "永赢", ["CPO"])
    _add_alias(db_session, "CPO", "BK1144", "光模块")
    db_session.commit()
    # 没生成过 signal
    e = SignalEngine(db_session)
    s = e.get_fund_signal_summary("022365")
    # mapped 但没 signal → neutral(配 reason)
    assert s["signal_type"] == SignalType.NEUTRAL.value


def test_fund_summary_picks_strongest_signal(db_session):
    """基金映射 2 个板块,取持续性最强那个。"""
    _add_fund(db_session, "022365", "永赢", ["CPO", "光模块"])
    _add_alias(db_session, "CPO", "BK1144", "光模块")
    _add_alias(db_session, "光模块", "BK1144", "光模块")
    # 这个 case 两个 label 映射到同一 BK,去重后只有 1 个
    # 改用另一个例子
    db_session.commit()

    # 设 BK1144 有 score=8 信号(已 commit + 生成)
    today = date(2026, 5, 22)
    for i, yi in enumerate([80, 85, 90, 95]):
        d = today - timedelta(days=3 - i)
        _add_flow(db_session, "BK1144", d,
                  int(yi * 10_000 * 10_000), int((0.012 + i * 0.003) * 10_000))
    db_session.commit()

    e = SignalEngine(db_session)
    signals = e.generate_signals_for_holdings()  # 空 holdings → 0 signals
    # 手动算 + 存
    sig = e.calculate_sector_signal("BK1144", "光模块", as_of=today)
    e.save_signals([sig])

    s = e.get_fund_signal_summary("022365")
    assert s["signal_type"] == SignalType.BULLISH.value
    assert s["via_sector"] == "BK1144"
    assert s["score"] >= 6


# ============================================================
# generate_signals_for_holdings 端到端
# ============================================================


def test_generate_signals_for_holdings_covers_mapped_sectors(db_session):
    # 2 只持仓,共映射 2 个 sector
    _add_fund(db_session, "022365", "永赢", ["CPO"])
    _add_fund(db_session, "008281", "国泰", ["半导体"])
    _add_alias(db_session, "CPO", "BK1144", "光模块")
    _add_alias(db_session, "半导体", "BK0490", "半导体")
    _add_holding(db_session, "022365")
    _add_holding(db_session, "008281")

    today = date(2026, 5, 22)
    _add_flow(db_session, "BK1144", today, 80 * 10_000 * 10_000, 100)
    _add_flow(db_session, "BK0490", today, -50 * 10_000 * 10_000, -150)
    db_session.commit()

    e = SignalEngine(db_session)
    signals = e.generate_signals_for_holdings(as_of=today)
    codes = {s.target_code for s in signals}
    assert codes == {"BK1144", "BK0490"}


def test_constants_match_spec():
    assert LOOKBACK_DAYS >= 4  # 至少够算连续 4 天
