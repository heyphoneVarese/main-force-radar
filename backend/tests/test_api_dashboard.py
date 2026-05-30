"""GET /api/dashboard/* 测试(market + sectors/top)。

只测路由 → DB 行为,不碰 akshare/scheduler。
"""

from datetime import date
from decimal import Decimal

import pytest

from src.models import MarketIndexDaily, SectorFlowDaily


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
