"""GET /api/dashboard/* 测试(market + sectors/top + holdings-summary)。

只测路由 → DB 行为,不碰 akshare/scheduler。
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.api import dashboard as dashboard_api
from src.models import (
    Fund,
    Holding,
    MarketIndexDaily,
    SectorAlias,
    SectorFlowDaily,
    Signal,
)


# PR19:默认 disable 4 个 extra 指数的即时拉取(它们走 sina 网络,测试里
# 既不可控也不该跑)。需要测 extras 的用例自己 explicit patch 上去。
@pytest.fixture(autouse=True)
def _disable_extra_index_fetch():
    dashboard_api._clear_extra_index_cache_for_test()
    with patch.object(
        dashboard_api, "_fetch_extra_index_with_cache", return_value=None
    ):
        yield
    dashboard_api._clear_extra_index_cache_for_test()


def _mk_index(
    code: str,
    name: str,
    trade_date: date,
    close_x10000: int,
    change_pct_x10000: int,
    turnover_wan_x10000: int | None = None,
) -> MarketIndexDaily:
    return MarketIndexDaily(
        index_code=code,
        index_name=name,
        trade_date=trade_date,
        close_x10000=close_x10000,
        change_pct_x10000=change_pct_x10000,
        turnover_wan_x10000=turnover_wan_x10000,
    )


# =====================================================================
# 空库
# =====================================================================


def test_market_endpoint_empty_db_returns_null_date(client):
    """库里完全没数据时,trade_date=null + 空 indices + HTTP 200。
    前端依赖这个语义渲染"今日数据未到"提示。"""
    resp = client.get("/api/dashboard/market")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["indices"] == []


# =====================================================================
# 单日 4 指数(主路径)
# =====================================================================


@pytest.fixture
def seed_one_day(db_session):
    """造一天 4 大指数。乱序入库,测试时验证 endpoint 按 DEFAULT_INDICES 排好。"""
    d = date(2026, 5, 30)
    rows = [
        # 故意乱序:沪深300 / 创业板 / 上证 / 深成
        _mk_index("sh000300", "沪深300", d, 41129000, 87, 18_000_000_0000),
        _mk_index("sz399006", "创业板指", d, 22035000, -23, 9_500_000_0000),
        _mk_index("sh000001", "上证指数", d, 31205000, 66, None),  # sina 无 turnover
        _mk_index("sz399001", "深证成指", d, 10120000, 41, 12_000_000_0000),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return d


def test_market_endpoint_returns_4_indices_in_default_order(client, seed_one_day):
    resp = client.get("/api/dashboard/market")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] == "2026-05-30"
    codes = [r["index_code"] for r in body["indices"]]
    # DEFAULT_INDICES 顺序:上证/深成/创业板/沪深300
    assert codes == ["sh000001", "sz399001", "sz399006", "sh000300"]


def test_market_endpoint_decimal_decoding_matches_money_module(client, seed_one_day):
    """close/change_pct/turnover 走 money 反算,跟 _x10000 整数语义一致。"""
    resp = client.get("/api/dashboard/market")
    indices = resp.json()["indices"]

    # 上证:close 31205000 → 3120.5;change_pct 66 → 0.0066;turnover_wan None
    sh = next(r for r in indices if r["index_code"] == "sh000001")
    assert Decimal(sh["close"]) == Decimal("3120.5")
    assert Decimal(sh["change_pct"]) == Decimal("0.0066")
    assert sh["turnover_wan"] is None

    # 沪深300:turnover_wan 18_000_000_0000 / 10000 = 18_000_000 万元
    hs300 = next(r for r in indices if r["index_code"] == "sh000300")
    assert Decimal(hs300["close"]) == Decimal("4112.9")
    assert Decimal(hs300["change_pct"]) == Decimal("0.0087")
    assert Decimal(hs300["turnover_wan"]) == Decimal("18000000")

    # 创业板:负涨跌幅 -23 → -0.0023
    cyb = next(r for r in indices if r["index_code"] == "sz399006")
    assert Decimal(cyb["change_pct"]) == Decimal("-0.0023")


# =====================================================================
# 多日 — 只返最新一天
# =====================================================================


def test_market_endpoint_returns_only_latest_trade_date(db_session, client):
    """库里 3 天数据,endpoint 只返最大 trade_date 的那一组。"""
    d1, d2, d3 = date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30)
    db_session.add_all([
        _mk_index("sh000001", "上证指数", d1, 31000000, 10),
        _mk_index("sh000001", "上证指数", d2, 31100000, 30),
        _mk_index("sh000001", "上证指数", d3, 31205000, 66),
        _mk_index("sz399001", "深证成指", d3, 10120000, 41),
    ])
    db_session.commit()

    resp = client.get("/api/dashboard/market")
    body = resp.json()
    assert body["trade_date"] == "2026-05-30"
    assert len(body["indices"]) == 2  # 只有 d3 那两条
    # 不应混入 d1/d2
    assert all(r["trade_date"] == "2026-05-30" for r in body["indices"])


def test_market_endpoint_partial_day_returns_what_exists(db_session, client):
    """最新一天只有 2 个指数(某 2 个 fetcher 失败)→ 只返 2 条,不补占位。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_index("sh000001", "上证指数", d, 31205000, 66),
        _mk_index("sz399006", "创业板指", d, 22035000, -23),
    ])
    db_session.commit()

    resp = client.get("/api/dashboard/market")
    body = resp.json()
    assert body["trade_date"] == "2026-05-30"
    codes = [r["index_code"] for r in body["indices"]]
    assert codes == ["sh000001", "sz399006"]  # 仍按 DEFAULT_INDICES 顺序


# =====================================================================
# 未知 index_code 兜底(理论上不发生,但路由不能崩)
# =====================================================================


def test_market_endpoint_unknown_index_code_sorted_to_tail(db_session, client):
    """如果库里出现 DEFAULT_INDICES 外的 code(如 sh000016 上证50),
    放到队尾,不丢数据也不报错。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_index("sh000016", "上证50", d, 38400000, 50),  # 不在 DEFAULT_INDICES
        _mk_index("sh000001", "上证指数", d, 31205000, 66),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/market").json()
    codes = [r["index_code"] for r in body["indices"]]
    # sh000001 在 DEFAULT_INDICES → 前;sh000016 不在 → 后
    assert codes == ["sh000001", "sh000016"]


# =====================================================================
# PR19 — market 8 指数扩展
# =====================================================================


def test_market_endpoint_includes_extras_when_fetcher_returns_data(
    db_session, client
):
    """DB 有 DEFAULT_INDICES 的 4 条 + extra fetcher 返 4 条 → 8 个全出。
    顺序按 DASHBOARD_DISPLAY_INDICES。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_index("sh000001", "上证指数", d, 31205000, 66),
        _mk_index("sz399001", "深证成指", d, 10120000, 41),
        _mk_index("sz399006", "创业板指", d, 22035000, -23),
        _mk_index("sh000300", "沪深300", d, 41129000, 87),
    ])
    db_session.commit()

    def _extra_stub(code, name):
        return {
            "index_code": code,
            "index_name": name,
            "trade_date": d,
            "close_x10000": 50000000,
            "change_pct_x10000": 100,
            "turnover_wan_x10000": None,
        }

    with patch.object(
        dashboard_api, "_fetch_extra_index_with_cache",
        side_effect=_extra_stub,
    ):
        body = client.get("/api/dashboard/market").json()

    codes = [r["index_code"] for r in body["indices"]]
    assert codes == [
        "sh000001", "sz399001", "sz399006", "sh000300",
        "sh000688", "sh000905", "sh000852", "bj899050",
    ]


def test_market_endpoint_extra_failures_dont_break_response(
    db_session, client
):
    """4 个 extra 全失败 → 仍能正常返 DB 里 4 个,HTTP 200。
    autouse fixture 默认 disable extras,刚好模拟这种 case。"""
    d = date(2026, 5, 30)
    db_session.add(_mk_index("sh000001", "上证指数", d, 31205000, 66))
    db_session.commit()

    body = client.get("/api/dashboard/market").json()
    assert body["trade_date"] == "2026-05-30"
    codes = [r["index_code"] for r in body["indices"]]
    assert codes == ["sh000001"]


def test_market_endpoint_one_extra_failure_others_ok(db_session, client):
    """3 个 extra 成,1 个失败 → 7 个出(4 DB + 3 extra)。"""
    d = date(2026, 5, 30)
    db_session.add(_mk_index("sh000001", "上证指数", d, 31205000, 66))
    db_session.commit()

    def _extra_stub(code, name):
        # 北证50 失败
        if code == "bj899050":
            return None
        return {
            "index_code": code,
            "index_name": name,
            "trade_date": d,
            "close_x10000": 50000000,
            "change_pct_x10000": 100,
            "turnover_wan_x10000": None,
        }

    with patch.object(
        dashboard_api, "_fetch_extra_index_with_cache",
        side_effect=_extra_stub,
    ):
        body = client.get("/api/dashboard/market").json()

    codes = [r["index_code"] for r in body["indices"]]
    # 1 个 DB + 3 个成功 extra(科创50/中证500/中证1000),北证50 缺
    assert codes == ["sh000001", "sh000688", "sh000905", "sh000852"]
    assert "bj899050" not in codes


def test_market_endpoint_only_extras_when_db_empty(db_session, client):
    """DB 完全空 + extra 全成 → 仍能返 4 个 extra,trade_date 来自 extra。"""
    extra_date = date(2026, 6, 1)

    def _extra_stub(code, name):
        return {
            "index_code": code,
            "index_name": name,
            "trade_date": extra_date,
            "close_x10000": 50000000,
            "change_pct_x10000": 100,
            "turnover_wan_x10000": None,
        }

    with patch.object(
        dashboard_api, "_fetch_extra_index_with_cache",
        side_effect=_extra_stub,
    ):
        body = client.get("/api/dashboard/market").json()

    assert body["trade_date"] == "2026-06-01"
    codes = [r["index_code"] for r in body["indices"]]
    assert codes == ["sh000688", "sh000905", "sh000852", "bj899050"]


# =====================================================================
# /api/dashboard/sectors/top
# =====================================================================


def _mk_sector(
    code: str,
    name: str,
    sector_type: str,
    trade_date: date,
    main_inflow_wan_x10000: int,
    main_inflow_pct_x10000: int | None = None,
    change_pct_x10000: int | None = None,
) -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        trade_date=trade_date,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        main_inflow_pct_x10000=main_inflow_pct_x10000,
        change_pct_x10000=change_pct_x10000,
    )


# ---- 空库 ----------------------------------------------------------


def test_sectors_top_empty_db_returns_null_date(client):
    resp = client.get("/api/dashboard/sectors/top")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["sector_type"] == "industry"  # 默认值
    assert body["sectors"] == []


# ---- 主路径:排序 + 限量 ------------------------------------------


@pytest.fixture
def seed_sectors_one_day(db_session):
    """造一天 6 个行业 + 3 个概念,故意乱序入库 + 含负值。"""
    d = date(2026, 5, 30)
    rows = [
        # 行业(industry) 6 个
        _mk_sector("BK0428", "电池", "industry", d, 520_000_0000, 830, 234),
        _mk_sector("BK0727", "半导体", "industry", d, 1_200_000_0000, 920, 312),
        _mk_sector("BK0420", "航空机场", "industry", d, -126_000_0000, -178, 138),
        _mk_sector("BK0429", "光伏设备", "industry", d, -180_000_0000, -310, -150),
        _mk_sector("BK0479", "证券", "industry", d, 300_000_0000, 450, 180),
        _mk_sector("BK0490", "通信设备", "industry", d, 80_000_0000, None, None),  # null pct
        # 概念(concept) 3 个
        _mk_sector("BK0739", "AI算力", "concept", d, 880_000_0000, 700, 280),
        _mk_sector("BK0888", "数字货币", "concept", d, 50_000_0000, 200, 90),
        _mk_sector("BK0999", "元宇宙", "concept", d, -300_000_0000, -500, -210),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return d


def test_sectors_top_industry_default_orders_by_inflow_desc(
    client, seed_sectors_one_day
):
    """默认 sector_type=industry,按 main_inflow_wan 降序。"""
    resp = client.get("/api/dashboard/sectors/top")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] == "2026-05-30"
    assert body["sector_type"] == "industry"
    # 6 个行业全部返回(默认 n=20 > 6)
    assert len(body["sectors"]) == 6
    # 按主力净流入降序:半导体 → 电池 → 证券 → 通信设备 → 航空机场 → 光伏设备
    codes = [s["sector_code"] for s in body["sectors"]]
    assert codes == ["BK0727", "BK0428", "BK0479", "BK0490", "BK0420", "BK0429"]
    # rank 1-based
    assert [s["rank"] for s in body["sectors"]] == [1, 2, 3, 4, 5, 6]


def test_sectors_top_respects_n_param(client, seed_sectors_one_day):
    """n=3 → 只返前 3 名;名次仍 1/2/3。"""
    body = client.get("/api/dashboard/sectors/top?n=3").json()
    assert len(body["sectors"]) == 3
    assert [s["rank"] for s in body["sectors"]] == [1, 2, 3]
    assert body["sectors"][0]["sector_code"] == "BK0727"  # 半导体


def test_sectors_top_filters_concept(client, seed_sectors_one_day):
    """sector_type=concept 只返概念板块,行业被滤掉。"""
    body = client.get("/api/dashboard/sectors/top?sector_type=concept").json()
    assert body["sector_type"] == "concept"
    codes = [s["sector_code"] for s in body["sectors"]]
    # AI算力 → 数字货币 → 元宇宙(降序;元宇宙是负值垫底)
    assert codes == ["BK0739", "BK0888", "BK0999"]
    assert all(s["sector_type"] == "concept" for s in body["sectors"])


def test_sectors_top_all_mixes_industry_and_concept(client, seed_sectors_one_day):
    """sector_type=all 不过滤,行业和概念按金额混排。"""
    body = client.get("/api/dashboard/sectors/top?sector_type=all").json()
    assert body["sector_type"] == "all"
    assert len(body["sectors"]) == 9  # 6 + 3
    # 半导体 (1.2e10) > AI算力 (8.8e9) > 电池 (5.2e9) > ...
    assert body["sectors"][0]["sector_code"] == "BK0727"  # 半导体
    assert body["sectors"][1]["sector_code"] == "BK0739"  # AI算力
    assert body["sectors"][2]["sector_code"] == "BK0428"  # 电池
    # 末位:元宇宙(-3e9 < 光伏设备 -1.8e9 < 航空 -1.26e9)
    assert body["sectors"][-1]["sector_code"] == "BK0999"  # 元宇宙


# ---- Decimal 解码 + nullable 字段 ---------------------------------


def test_sectors_top_decimal_decoding(client, seed_sectors_one_day):
    """main_inflow_wan / main_inflow_pct / change_pct 走 money 反算。"""
    body = client.get("/api/dashboard/sectors/top?n=1").json()
    s = body["sectors"][0]  # 半导体
    # main_inflow_wan_x10000 = 12_000_000_000 → / 10000 = 1_200_000(万元 = 12 亿元)
    assert Decimal(s["main_inflow_wan"]) == Decimal("1200000")
    # 920 / 10000 = 0.092 = 9.2%
    assert Decimal(s["main_inflow_pct"]) == Decimal("0.092")
    # 312 / 10000 = 0.0312 = 3.12%
    assert Decimal(s["change_pct"]) == Decimal("0.0312")


def test_sectors_top_null_pct_fields_preserved(client, seed_sectors_one_day):
    """通信设备的 main_inflow_pct 和 change_pct 都是 None → JSON 里仍是 null。"""
    body = client.get("/api/dashboard/sectors/top?n=20").json()
    tx = next(s for s in body["sectors"] if s["sector_code"] == "BK0490")
    assert tx["main_inflow_pct"] is None
    assert tx["change_pct"] is None
    # main_inflow_wan_x10000=800_000_000 → / 10000 = 80_000 万元(= 8 亿元)
    assert Decimal(tx["main_inflow_wan"]) == Decimal("80000")


def test_sectors_top_negative_inflow_decoded_with_sign(client, seed_sectors_one_day):
    """光伏 / 航空 / 元宇宙 都是负值:JSON 里负号必须保留。"""
    body = client.get("/api/dashboard/sectors/top?sector_type=all").json()
    pv = next(s for s in body["sectors"] if s["sector_code"] == "BK0429")  # 光伏
    # main_inflow_wan_x10000=-1_800_000_000 → / 10000 = -180_000 万元(= -18 亿元)
    assert Decimal(pv["main_inflow_wan"]) == Decimal("-180000")
    # change_pct_x10000=-150 → / 10000 = -0.015 = -1.5%
    assert Decimal(pv["change_pct"]) == Decimal("-0.015")


# ---- 多日 — 只返最新 ---------------------------------------------


def test_sectors_top_returns_only_latest_trade_date(db_session, client):
    d1, d2 = date(2026, 5, 29), date(2026, 5, 30)
    db_session.add_all([
        _mk_sector("BK0001", "旧板块", "industry", d1, 999_999_0000),
        _mk_sector("BK0002", "新板块", "industry", d2, 100_0000),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/sectors/top").json()
    assert body["trade_date"] == "2026-05-30"
    codes = [s["sector_code"] for s in body["sectors"]]
    assert codes == ["BK0002"]  # 不应混入 d1


# ---- 参数校验 -----------------------------------------------------


def test_sectors_top_invalid_n_rejected(client):
    """n 出界(<1 或 >100)→ 422。"""
    assert client.get("/api/dashboard/sectors/top?n=0").status_code == 422
    assert client.get("/api/dashboard/sectors/top?n=101").status_code == 422


def test_sectors_top_invalid_sector_type_rejected(client):
    """非法 sector_type → 422。"""
    resp = client.get("/api/dashboard/sectors/top?sector_type=region")  # 暂不开放
    assert resp.status_code == 422
    resp = client.get("/api/dashboard/sectors/top?sector_type=bogus")
    assert resp.status_code == 422


# =====================================================================
# /api/dashboard/holdings-summary
# =====================================================================


def _mk_fund(
    code: str, name: str, related_sectors: list[str] | None = None
) -> Fund:
    return Fund(
        fund_code=code,
        fund_name=name,
        fund_type="混合",
        related_sectors=related_sectors,
    )


def _mk_holding(code: str) -> Holding:
    """最简持仓:占位 cost/shares,bought_at 任意。"""
    return Holding(
        fund_code=code,
        cost_nav_x10000=10000,           # 1.0000
        shares_x100=1_000_000,           # 10000.00
        bought_at=date(2025, 1, 1),
    )


def _mk_alias(label: str, sector_code: str | None, sector_name: str) -> SectorAlias:
    return SectorAlias(
        chinese_label=label,
        sector_code=sector_code,
        sector_name=sector_name,
        confidence=1.0,
    )


def _mk_alias_with_conf(
    label: str,
    sector_code: str | None,
    sector_name: str,
    confidence: float,
) -> SectorAlias:
    return SectorAlias(
        chinese_label=label,
        sector_code=sector_code,
        sector_name=sector_name,
        confidence=confidence,
    )


def _mk_signal(
    sector_code: str,
    trade_date: date,
    signal_type: str,
    persistence_score: int,
    main_inflow_wan_x10000: int,
) -> Signal:
    return Signal(
        trade_date=trade_date,
        signal_type=signal_type,
        target_type="sector",
        target_code=sector_code,
        signal_name=f"{sector_code} {signal_type}",
        description="test",
        score_x100=persistence_score * 100,
        persistence_score=persistence_score,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        triggered_at=datetime(trade_date.year, trade_date.month, trade_date.day, 15, 30),
    )


# ---- 空库 ----------------------------------------------------------


def test_holdings_summary_empty_db_returns_empty(client):
    """无持仓 → 200 + {trade_date: null, holdings: []}。"""
    resp = client.get("/api/dashboard/holdings-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["holdings"] == []


# ---- not_applicable(QDII 类,related_sectors 为 null)----


def test_holdings_summary_not_applicable_when_no_related_sectors(db_session, client):
    """QDII/指数/债基:funds.related_sectors=None → signal_type=not_applicable,
    所有数值字段 null。"""
    db_session.add_all([
        _mk_fund("006479", "广发纳斯达克100ETF联接(QDII)C", related_sectors=None),
        _mk_holding("006479"),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/holdings-summary").json()
    assert body["trade_date"] is None  # 无 via_sector 就无 trade_date
    assert len(body["holdings"]) == 1
    h = body["holdings"][0]
    assert h["fund_code"] == "006479"
    assert h["fund_name"] == "广发纳斯达克100ETF联接(QDII)C"
    assert h["related_sectors"] == []
    assert h["signal_type"] == "not_applicable"
    assert h["persistence_score"] == 0
    assert h["via_sector"] is None
    assert h["main_inflow_wan"] is None
    assert h["change_pct"] is None
    assert "未映射" in h["reason"]


# ---- 完整数据路径(Fund + Alias + Signal + SectorFlowDaily)----


@pytest.fixture
def seed_full_holding(db_session):
    """造一只 fund 映射到 BK0727 半导体,Signal + sector_flow_daily 都齐。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("008281", "国泰CES半导体芯片行业ETF联接A",
                 related_sectors=["半导体"]),
        _mk_holding("008281"),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_signal("BK0727", d, "bullish",
                   persistence_score=8, main_inflow_wan_x10000=12_000_000_000),
        SectorFlowDaily(
            sector_code="BK0727",
            sector_name="半导体",
            sector_type="industry",
            trade_date=d,
            main_inflow_wan_x10000=12_000_000_000,
            main_inflow_pct_x10000=920,
            change_pct_x10000=312,
        ),
    ])
    db_session.commit()
    return d


def test_holdings_summary_full_path_all_fields_populated(client, seed_full_holding):
    body = client.get("/api/dashboard/holdings-summary").json()
    assert body["trade_date"] == "2026-05-30"
    assert len(body["holdings"]) == 1
    h = body["holdings"][0]
    assert h["fund_code"] == "008281"
    assert h["fund_name"] == "国泰CES半导体芯片行业ETF联接A"
    assert h["related_sectors"] == ["半导体"]
    assert h["signal_type"] == "bullish"
    assert h["persistence_score"] == 8
    assert h["via_sector"] == "BK0727"
    # 12_000_000_000 / 10000 = 1_200_000 万元
    assert Decimal(h["main_inflow_wan"]) == Decimal("1200000")
    # 312 / 10000 = 0.0312
    assert Decimal(h["change_pct"]) == Decimal("0.0312")
    assert "score=8" in h["reason"]


# ---- Signal 有但 sector_flow_daily 同日无行 ---------------------


def test_holdings_summary_signal_without_sector_flow_keeps_change_pct_null(
    db_session, client
):
    """Signal 存了 main_inflow_wan,但 sector_flow_daily 那天没数据
    → main_inflow_wan 仍有(从 Signal 拿),change_pct = null。
    可能发生场景:scheduler 拉 sector_flow 失败,但 generate_signals 用旧 flow 算过分。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F0001", "测试基金", related_sectors=["半导体"]),
        _mk_holding("F0001"),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_signal("BK0727", d, "bullish",
                   persistence_score=7, main_inflow_wan_x10000=5_000_000_000),
        # 故意不加 SectorFlowDaily 行
    ])
    db_session.commit()

    h = client.get("/api/dashboard/holdings-summary").json()["holdings"][0]
    assert h["via_sector"] == "BK0727"
    assert Decimal(h["main_inflow_wan"]) == Decimal("500000")  # 来自 Signal
    assert h["change_pct"] is None  # sector_flow 没有就是 None


# ---- 映射板块但无任何 Signal(scheduler 没跑过)-----------------


def test_holdings_summary_mapped_but_no_signal_returns_neutral(db_session, client):
    """sector 映射有,但 Signal 表里这个 sector 一条都没有(信号引擎还没跑)
    → signal_type=neutral,via_sector=null,reason 提示采集。"""
    db_session.add_all([
        _mk_fund("F0002", "测试基金", related_sectors=["半导体"]),
        _mk_holding("F0002"),
        _mk_alias("半导体", "BK0727", "半导体"),
        # 故意不加 Signal
    ])
    db_session.commit()

    h = client.get("/api/dashboard/holdings-summary").json()["holdings"][0]
    assert h["signal_type"] == "neutral"
    assert h["persistence_score"] == 0
    assert h["via_sector"] is None
    assert h["main_inflow_wan"] is None
    assert h["change_pct"] is None
    assert "无 sector_flow" in h["reason"] or "请先采集" in h["reason"]


def test_holdings_summary_low_confidence_alias_not_applicable(db_session, client):
    db_session.add_all([
        _mk_fund("F_LOW", "光伏基金", related_sectors=["光伏"]),
        _mk_holding("F_LOW"),
        _mk_alias_with_conf("光伏", "BK0429", "光伏设备", 0.6),
        _mk_signal(
            "BK0429",
            date(2026, 5, 30),
            "bullish",
            persistence_score=8,
            main_inflow_wan_x10000=12_000_000_000,
        ),
    ])
    db_session.commit()

    h = client.get("/api/dashboard/holdings-summary").json()["holdings"][0]
    assert h["signal_type"] == "not_applicable"
    assert h["via_sector"] is None
    assert h["main_inflow_wan"] is None


# ---- 多板块,via_sector 取分最高 ---------------------------------


def test_holdings_summary_picks_strongest_sector_as_via(db_session, client):
    """一只基金映射到 2 个板块,via_sector 取持续性分最高的那个。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F0003", "双板块基金", related_sectors=["半导体", "AI算力"]),
        _mk_holding("F0003"),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_alias("AI算力", "BK0739", "AI算力"),
        # 半导体 score=5(普通),AI 算力 score=8(强)→ via_sector 应该是 AI 算力
        _mk_signal("BK0727", d, "neutral",
                   persistence_score=5, main_inflow_wan_x10000=2_000_000_000),
        _mk_signal("BK0739", d, "bullish",
                   persistence_score=8, main_inflow_wan_x10000=8_000_000_000),
    ])
    db_session.commit()

    h = client.get("/api/dashboard/holdings-summary").json()["holdings"][0]
    assert h["via_sector"] == "BK0739"  # AI算力 score 高
    assert h["signal_type"] == "bullish"
    assert h["persistence_score"] == 8
    assert Decimal(h["main_inflow_wan"]) == Decimal("800000")  # 8e9/1e4
    # related_sectors 显示原始两个标签(都在)
    assert set(h["related_sectors"]) == {"半导体", "AI算力"}


# ---- 多持仓:排序 + trade_date 聚合 ------------------------------


def test_holdings_summary_orders_by_fund_code_and_aggregates_trade_date(
    db_session, client
):
    """3 只持仓:fund_code 字典序输出;顶层 trade_date 取所有 via_sector
    Signal 中最大的那个。"""
    d_early = date(2026, 5, 28)
    d_late = date(2026, 5, 30)
    db_session.add_all([
        # F0010 → 半导体(信号 5/28 — 旧),F0020 → AI(信号 5/30 — 新)
        _mk_fund("F0020", "Beta基金", related_sectors=["AI算力"]),
        _mk_fund("F0010", "Alpha基金", related_sectors=["半导体"]),
        _mk_holding("F0010"),
        _mk_holding("F0020"),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_alias("AI算力", "BK0739", "AI算力"),
        _mk_signal("BK0727", d_early, "bullish",
                   persistence_score=7, main_inflow_wan_x10000=3_000_000_000),
        _mk_signal("BK0739", d_late, "bullish",
                   persistence_score=8, main_inflow_wan_x10000=8_000_000_000),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/holdings-summary").json()
    # 顶层 trade_date = max(d_early, d_late) = 5/30
    assert body["trade_date"] == "2026-05-30"
    # holdings 按 fund_code 升序:F0010 在前
    codes = [h["fund_code"] for h in body["holdings"]]
    assert codes == ["F0010", "F0020"]


# ---- 混合状态(not_applicable + 完整 + neutral)---------------


def test_holdings_summary_handles_mixed_states_in_same_response(db_session, client):
    """同一响应里混着 not_applicable / bullish / neutral 三种状态,
    各自字段语义正确。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        # A: QDII not_applicable
        _mk_fund("F_A", "QDII基金", related_sectors=None),
        _mk_holding("F_A"),
        # B: bullish(全数据)
        _mk_fund("F_B", "半导体基金", related_sectors=["半导体"]),
        _mk_holding("F_B"),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_signal("BK0727", d, "bullish",
                   persistence_score=8, main_inflow_wan_x10000=12_000_000_000),
        # C: 有 alias 但无 Signal → neutral
        _mk_fund("F_C", "新基金", related_sectors=["医药"]),
        _mk_holding("F_C"),
        _mk_alias("医药", "BK0727_X", "医药生物"),  # 故意没建 signal
    ])
    db_session.commit()

    body = client.get("/api/dashboard/holdings-summary").json()
    assert body["trade_date"] == "2026-05-30"  # F_B 撑起 trade_date
    assert len(body["holdings"]) == 3
    by_code = {h["fund_code"]: h for h in body["holdings"]}

    # A:not_applicable
    assert by_code["F_A"]["signal_type"] == "not_applicable"
    assert by_code["F_A"]["via_sector"] is None
    # B:bullish 全字段
    assert by_code["F_B"]["signal_type"] == "bullish"
    assert by_code["F_B"]["via_sector"] == "BK0727"
    assert Decimal(by_code["F_B"]["main_inflow_wan"]) == Decimal("1200000")
    # C:neutral
    assert by_code["F_C"]["signal_type"] == "neutral"
    assert by_code["F_C"]["via_sector"] is None


# ---- bearish 路径:负流入也能正确解码 ---------------------------


def test_holdings_summary_bearish_signal_with_negative_inflow(db_session, client):
    """退潮板块:main_inflow_wan_x10000 是大负数,API 输出 Decimal 也带负号。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_BEAR", "光伏基金", related_sectors=["光伏设备"]),
        _mk_holding("F_BEAR"),
        _mk_alias("光伏设备", "BK0429", "光伏设备"),
        _mk_signal("BK0429", d, "bearish",
                   persistence_score=8, main_inflow_wan_x10000=-1_800_000_000),
        SectorFlowDaily(
            sector_code="BK0429",
            sector_name="光伏设备",
            sector_type="industry",
            trade_date=d,
            main_inflow_wan_x10000=-1_800_000_000,
            main_inflow_pct_x10000=-310,
            change_pct_x10000=-150,
        ),
    ])
    db_session.commit()

    h = client.get("/api/dashboard/holdings-summary").json()["holdings"][0]
    assert h["signal_type"] == "bearish"
    # -1_800_000_000 / 10000 = -180_000 万元
    assert Decimal(h["main_inflow_wan"]) == Decimal("-180000")
    assert Decimal(h["change_pct"]) == Decimal("-0.015")


# =====================================================================
# /api/dashboard/funds/top
# =====================================================================


def _mk_flow_row(
    sector_code: str,
    sector_name: str,
    trade_date: date,
    main_inflow_wan_x10000: int,
    change_pct_x10000: int | None = None,
    main_inflow_pct_x10000: int | None = None,
    sector_type: str = "industry",
) -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=sector_code,
        sector_name=sector_name,
        sector_type=sector_type,
        trade_date=trade_date,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        main_inflow_pct_x10000=main_inflow_pct_x10000,
        change_pct_x10000=change_pct_x10000,
    )


# ---- 空状态 ------------------------------------------------------


def test_funds_top_empty_db_returns_empty(client):
    """完全空库 → 200 + {trade_date: null, funds: []}。"""
    resp = client.get("/api/dashboard/funds/top")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["funds"] == []


def test_funds_top_funds_exist_but_no_sector_flow_returns_empty(db_session, client):
    """funds 表非空但 sector_flow_daily 空 → 没排序键 → funds=[]。"""
    db_session.add(_mk_fund("F001", "测试基金", related_sectors=["半导体"]))
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    assert body["trade_date"] is None
    assert body["funds"] == []


# ---- 过滤策略(无数据不上榜)-----------------------------------


def test_funds_top_excludes_funds_without_related_sectors(db_session, client):
    """QDII 类 fund(related_sectors=None)不返回。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_QDII", "纳指基金", related_sectors=None),
        _mk_fund("F_OK", "半导体基金", related_sectors=["半导体"]),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_flow_row("BK0727", "半导体", d, 12_000_000_000, change_pct_x10000=312),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    codes = [f["fund_code"] for f in body["funds"]]
    assert codes == ["F_OK"]


def test_funds_top_excludes_funds_with_unmapped_labels(db_session, client):
    """fund.related_sectors 有标签,但 sector_aliases 没建过条目 → 不上榜。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_UNMAPPED", "冷门标签基金", related_sectors=["元宇宙"]),
        _mk_fund("F_OK", "半导体基金", related_sectors=["半导体"]),
        _mk_alias("半导体", "BK0727", "半导体"),
        # 故意不加 "元宇宙" alias
        _mk_flow_row("BK0727", "半导体", d, 12_000_000_000),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    codes = [f["fund_code"] for f in body["funds"]]
    assert codes == ["F_OK"]


def test_funds_top_excludes_funds_with_no_flow_data_for_mapped_sectors(
    db_session, client
):
    """sector 映射有,但当日 sector_flow_daily 这个 BK 没数据 → 不上榜。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_NODATA", "医药基金", related_sectors=["医药"]),
        _mk_fund("F_OK", "半导体基金", related_sectors=["半导体"]),
        _mk_alias("医药", "BK0719", "医药生物"),  # alias 有
        _mk_alias("半导体", "BK0727", "半导体"),
        # 故意只造半导体 sector_flow,不造医药的
        _mk_flow_row("BK0727", "半导体", d, 12_000_000_000),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    codes = [f["fund_code"] for f in body["funds"]]
    assert codes == ["F_OK"]


# ---- 主路径:排序 + 字段 ----------------------------------------


@pytest.fixture
def seed_top_funds(db_session):
    """3 只基金 → 3 个不同强度的板块,验证排序。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_STRONG", "半导体基金", related_sectors=["半导体"]),
        _mk_fund("F_MID", "证券基金", related_sectors=["证券"]),
        _mk_fund("F_WEAK", "光伏基金", related_sectors=["光伏设备"]),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_alias("证券", "BK0479", "证券"),
        _mk_alias("光伏设备", "BK0429", "光伏设备"),
        _mk_flow_row("BK0727", "半导体", d, 12_000_000_000, change_pct_x10000=312),
        _mk_flow_row("BK0479", "证券", d, 3_000_000_000, change_pct_x10000=180),
        _mk_flow_row("BK0429", "光伏设备", d, -1_800_000_000, change_pct_x10000=-150),
    ])
    db_session.commit()
    return d


def test_funds_top_orders_by_via_inflow_desc(client, seed_top_funds):
    body = client.get("/api/dashboard/funds/top").json()
    assert body["trade_date"] == "2026-05-30"
    assert [f["fund_code"] for f in body["funds"]] == ["F_STRONG", "F_MID"]
    assert [f["rank"] for f in body["funds"]] == [1, 2]


def test_funds_top_negative_inflow_excluded(client, seed_top_funds):
    """负流入基金不进入最强候选。"""
    body = client.get("/api/dashboard/funds/top").json()
    codes = [f["fund_code"] for f in body["funds"]]
    assert "F_WEAK" not in codes
    assert all(Decimal(f["main_inflow_wan"]) > 0 for f in body["funds"])


def test_funds_top_all_negative_returns_empty(db_session, client):
    """全部 verified 映射都是净流出时,返回空列表。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_A", "通信基金", related_sectors=["通信服务"]),
        _mk_fund("F_B", "AI 基金", related_sectors=["人工智能"]),
        _mk_alias("通信服务", "BK0448", "通信服务"),
        _mk_alias("人工智能", "BK0739", "人工智能"),
        _mk_flow_row("BK0448", "通信服务", d, -6_600_000_000),
        _mk_flow_row("BK0739", "人工智能", d, -7_400_000_000),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/funds/top").json()
    assert body["trade_date"] == "2026-05-30"
    assert body["funds"] == []
    assert "freshness" in body
    assert "time_meta" in body


def test_funds_top_respects_n_param(client, seed_top_funds):
    body = client.get("/api/dashboard/funds/top?n=2").json()
    assert len(body["funds"]) == 2
    assert [f["rank"] for f in body["funds"]] == [1, 2]
    assert body["funds"][0]["fund_code"] == "F_STRONG"


def test_funds_top_decimal_decoding(client, seed_top_funds):
    body = client.get("/api/dashboard/funds/top").json()
    top = body["funds"][0]
    # 12_000_000_000 / 10000 = 1_200_000 万元(= 120 亿元)
    assert Decimal(top["main_inflow_wan"]) == Decimal("1200000")
    # 312 / 10000 = 0.0312
    assert Decimal(top["change_pct"]) == Decimal("0.0312")


def test_funds_top_returns_explicit_mapping_fields(client, seed_top_funds):
    body = client.get("/api/dashboard/funds/top").json()
    top = body["funds"][0]
    assert top["via_sector_code"] == "BK0727"
    assert top["via_sector_name"] == "半导体"
    assert top["mapping_confidence"] == 1.0
    assert top["mapping_status"] == "verified"
    assert top["mapping_source"] == "sector_aliases"
    assert "freshness" in body
    assert "time_meta" in body


def test_funds_top_excludes_low_confidence_mapping_from_ranking(
    db_session, client
):
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_LOW", "光伏基金", related_sectors=["光伏"]),
        _mk_fund("F_OK", "半导体基金", related_sectors=["半导体"]),
        _mk_alias_with_conf("光伏", "BK0429", "光伏设备", 0.6),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_flow_row("BK0429", "光伏设备", d, 100_000_000_000),
        _mk_flow_row("BK0727", "半导体", d, 1_000_000_000),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/funds/top").json()
    assert [f["fund_code"] for f in body["funds"]] == ["F_OK"]


# ---- 多板块基金:via 取 max,matched_sectors 全列 ---------------


def test_funds_top_multi_sector_picks_max_inflow_as_via(db_session, client):
    """一只基金映射到 2 个板块 → via_sector 取流入最大的那个;
    matched_sectors 含两个。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_DUAL", "AI+半导体基金", related_sectors=["半导体", "AI算力"]),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_alias("AI算力", "BK0739", "AI算力"),
        # AI 流入 8e9,半导体 5e9 → via 应该是 AI
        _mk_flow_row("BK0727", "半导体", d, 5_000_000_000, change_pct_x10000=200),
        _mk_flow_row("BK0739", "AI算力", d, 8_000_000_000, change_pct_x10000=280),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    f = body["funds"][0]
    # via = AI算力 → main_inflow_wan = 8e9/1e4 = 800_000
    assert Decimal(f["main_inflow_wan"]) == Decimal("800000")
    assert Decimal(f["change_pct"]) == Decimal("0.028")
    # matched_sectors 含两个,且带 sector_name
    codes = {m["sector_code"] for m in f["matched_sectors"]}
    assert codes == {"BK0727", "BK0739"}
    names = {m["sector_name"] for m in f["matched_sectors"]}
    assert names == {"半导体", "AI算力"}
    # related_sectors 透传原始中文标签
    assert set(f["related_sectors"]) == {"半导体", "AI算力"}
    # reason 含 via_sector 名 + 持续性
    assert "AI算力" in f["reason"] and "BK0739" in f["reason"]


def test_funds_top_matched_sectors_excludes_unfeed_codes(db_session, client):
    """fund 映射到 2 个 BK,但只有 1 个当日有 sector_flow → matched_sectors 只列那个 1 个。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_PARTIAL", "部分映射基金", related_sectors=["半导体", "医药"]),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_alias("医药", "BK0719", "医药生物"),
        _mk_flow_row("BK0727", "半导体", d, 5_000_000_000),  # 只有半导体有数据
    ])
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    f = body["funds"][0]
    assert [m["sector_code"] for m in f["matched_sectors"]] == ["BK0727"]
    # related_sectors 仍是原始两个(没数据的也展示)
    assert set(f["related_sectors"]) == {"半导体", "医药"}


# ---- 多日数据 — 只用最新 ----------------------------------------


def test_funds_top_uses_only_latest_sector_flow_date(db_session, client):
    """sector_flow_daily 有 d1 d2 两天 → 只用 d2 的数据;旧日 d1 不污染。"""
    d1, d2 = date(2026, 5, 29), date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_A", "基金 A", related_sectors=["半导体"]),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_flow_row("BK0727", "半导体", d1, 100_000_000_000),  # d1 假设巨大
        _mk_flow_row("BK0727", "半导体", d2, 1_000_000_000),    # d2 较小
    ])
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    assert body["trade_date"] == "2026-05-30"
    # 用 d2 的 1_000_000_000 / 10000 = 100_000 万元;不应用 d1 的巨值
    assert Decimal(body["funds"][0]["main_inflow_wan"]) == Decimal("100000")


# ---- score:多日数据 → 持续性 > 0 -----------------------------


def test_funds_top_score_reflects_persistence_when_multi_day_data(db_session, client):
    """造连续 3 天大额净流入 + 量价齐升 → 持续性 score 应该 > 0。
    具体值由 SignalEngine 算,这里只断言 > 0。"""
    d1, d2, d3 = date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30)
    db_session.add_all([
        _mk_fund("F_PERSIST", "强基金", related_sectors=["半导体"]),
        _mk_alias("半导体", "BK0727", "半导体"),
        # 3 天连续大额净流入 + 量递增(today > yest)+ change_pct 同号
        _mk_flow_row("BK0727", "半导体", d1, 5_000_000_000, change_pct_x10000=100),
        _mk_flow_row("BK0727", "半导体", d2, 8_000_000_000, change_pct_x10000=150),
        _mk_flow_row("BK0727", "半导体", d3, 12_000_000_000, change_pct_x10000=312),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/funds/top").json()
    f = body["funds"][0]
    # base(>100亿=4) + continuity(3天=2) + vol_price(量增同号=2) = 8/9
    assert f["score"] == 8
    assert "持续性 8/9" in f["reason"]


# ---- 参数校验 ----------------------------------------------------


def test_funds_top_invalid_n_rejected(client):
    assert client.get("/api/dashboard/funds/top?n=0").status_code == 422
    assert client.get("/api/dashboard/funds/top?n=101").status_code == 422
