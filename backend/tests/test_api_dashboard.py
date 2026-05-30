"""GET /api/dashboard/market 测试。

只测路由 → DB 行为,不碰 akshare/scheduler。
"""

from datetime import date
from decimal import Decimal

import pytest

from src.models import MarketIndexDaily


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
