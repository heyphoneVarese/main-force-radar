"""data_fetcher 测试 — 用 mock 隔离 akshare 网络调用,保证 CI 快/稳/无网。"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.services import data_fetcher as df_mod


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    """关掉 retry 之间的 sleep,让测试秒级跑完。"""
    monkeypatch.setattr(df_mod, "RETRY_DELAY_SEC", 0)


# =====================================================================
# fixtures
# =====================================================================


@pytest.fixture
def fake_sector_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "名称": "电池",
                "代码": "BK0428",
                "今日涨跌幅": 2.34,
                "今日主力净流入-净额": 520_000_000.0,  # 5.2 亿元
                "今日主力净流入-净占比": 8.3,
            },
            {
                "名称": "光伏设备",
                "代码": "BK0429",
                "今日涨跌幅": -1.5,
                "今日主力净流入-净额": -180_000_000.0,  # -1.8 亿元
                "今日主力净流入-净占比": -3.1,
            },
        ]
    )


@pytest.fixture
def fake_index_df() -> pd.DataFrame:
    """sina stock_zh_index_daily 实际返回的列:date / open / high / low / close / volume(无 amount)。"""
    return pd.DataFrame(
        [
            {"date": "2026-05-23", "open": 3090.0, "high": 3110.0, "low": 3080.0,
             "close": 3100.0, "volume": 200_000_000},
            {"date": "2026-05-24", "open": 3105.0, "high": 3125.0, "low": 3098.0,
             "close": 3120.5, "volume": 230_000_000},
        ]
    )


# =====================================================================
# 正常路径
# =====================================================================


def test_fetch_sector_flow_industry_returns_normalized_rows(fake_sector_df):
    with patch(
        "src.services.data_fetcher.ak.stock_sector_fund_flow_rank",
        return_value=fake_sector_df,
        create=True,
    ):
        rows = df_mod.fetch_sector_flow_industry()

    assert len(rows) == 2

    # R1: 金额字段必须 int
    for r in rows:
        assert isinstance(r["main_inflow_wan_x10000"], int)
        assert isinstance(r["change_pct_x10000"], int)
        assert isinstance(r["main_inflow_pct_x10000"], int)
        assert r["sector_type"] == "industry"

    # 5.2 亿 = 52000 万元 × 10000 = 520_000_000
    assert rows[0]["main_inflow_wan_x10000"] == 520_000_000
    # 涨跌幅 2.34% = 0.0234 × 10000 = 234
    assert rows[0]["change_pct_x10000"] == 234
    # 负流出:-1.8 亿元 = -18000 万元 × 10000 = -180_000_000
    assert rows[1]["main_inflow_wan_x10000"] == -180_000_000


def test_fetch_sector_flow_concept_uses_concept_label(fake_sector_df):
    with patch(
        "src.services.data_fetcher.ak.stock_sector_fund_flow_rank",
        return_value=fake_sector_df,
        create=True,
    ):
        rows = df_mod.fetch_sector_flow_concept()
    assert all(r["sector_type"] == "concept" for r in rows)


def test_fetch_market_index_sina(fake_index_df):
    """sina 数据源:无 amount 列,turnover_wan_x10000 应为 None。"""
    with patch(
        "src.services.data_fetcher.ak.stock_zh_index_daily",
        return_value=fake_index_df,
        create=True,
    ):
        rows = df_mod.fetch_market_index("sh000001")

    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r["close_x10000"], int)
    assert isinstance(r["change_pct_x10000"], int)
    # 3120.5 × 10000 = 31_205_000
    assert r["close_x10000"] == 31_205_000
    # 涨跌幅 (3120.5 - 3100) / 3100 ≈ 0.006612... × 10000 ≈ 66 bps
    assert r["change_pct_x10000"] == 66
    # sina 无 amount,turnover 应为 None
    assert r["turnover_wan_x10000"] is None


# =====================================================================
# 异常路径:不抛,返回空
# =====================================================================


def test_fetch_sector_flow_returns_empty_on_network_error():
    with patch(
        "src.services.data_fetcher.ak.stock_sector_fund_flow_rank",
        side_effect=ConnectionError("network down"),
        create=True,
    ):
        rows = df_mod.fetch_sector_flow_industry()
    assert rows == []


def test_fetch_market_index_returns_empty_on_exception():
    with patch(
        "src.services.data_fetcher.ak.stock_zh_index_daily",
        side_effect=Exception("dead"),
        create=True,
    ):
        rows = df_mod.fetch_market_index("sh000001")
    assert rows == []


def test_fetch_sector_flow_returns_empty_on_empty_df():
    with patch(
        "src.services.data_fetcher.ak.stock_sector_fund_flow_rank",
        return_value=pd.DataFrame(),
        create=True,
    ):
        rows = df_mod.fetch_sector_flow_industry()
    assert rows == []


def test_fetch_fund_nav_returns_empty_on_exception():
    with patch(
        "src.services.data_fetcher.ak.fund_open_fund_info_em",
        side_effect=Exception("boom"),
        create=True,
    ):
        rows = df_mod.fetch_fund_nav("000001")
    assert rows == []


def test_fetch_fund_holdings_returns_empty_on_exception():
    with patch(
        "src.services.data_fetcher.ak.fund_portfolio_hold_em",
        side_effect=Exception("boom"),
        create=True,
    ):
        rows = df_mod.fetch_fund_holdings("000001")
    assert rows == []


# =====================================================================
# 重试 3 次
# =====================================================================


def test_retry_attempts_exactly_3_times_then_returns_fallback():
    mock = MagicMock(side_effect=ConnectionError("boom"))
    with patch(
        "src.services.data_fetcher.ak.stock_sector_fund_flow_rank",
        new=mock,
        create=True,
    ):
        rows = df_mod.fetch_sector_flow_industry()

    assert rows == []
    assert mock.call_count == 3


# =====================================================================
# fetch_and_store_today + insert helpers(Phase 4.x daily_fetch 用)
# =====================================================================

from datetime import date as _date


def _mk_sector_row(sector_code: str, name: str, inflow_yi: float, change_pct: float):
    """构造一个 sector_flow_daily 入库 dict。"""
    return {
        "trade_date": _date(2026, 5, 27),
        "sector_code": sector_code,
        "sector_name": name,
        "sector_type": "industry",
        "main_inflow_wan_x10000": int(inflow_yi * 10_000 * 10_000),
        "main_inflow_pct_x10000": None,
        "change_pct_x10000": int(change_pct * 10_000),
    }


def _mk_index_row(code: str):
    """构造一个 market_index_daily 入库 dict(fetcher 默认 index_name=code 占位)。"""
    return {
        "index_code": code,
        "index_name": code,
        "trade_date": _date(2026, 5, 27),
        "close_x10000": 41129000,
        "change_pct_x10000": 87,
        "turnover_wan_x10000": None,
    }


def test_insert_sector_flow_rows_inserts_new(db_session):
    rows = [_mk_sector_row("BK0490", "半导体", 95.0, 0.0234)]
    n = df_mod.insert_sector_flow_rows(db_session, rows)
    assert n == 1


def test_insert_sector_flow_rows_skips_existing(db_session):
    rows = [_mk_sector_row("BK0490", "半导体", 95.0, 0.0234)]
    df_mod.insert_sector_flow_rows(db_session, rows)
    # 同一 (trade_date, sector_code) 再插一次,应跳过
    n2 = df_mod.insert_sector_flow_rows(db_session, rows)
    assert n2 == 0


def test_insert_market_index_rows_overrides_name(db_session):
    rows = [_mk_index_row("sh000001")]
    df_mod.insert_market_index_rows(db_session, rows, index_name="上证指数")
    # 查回来确认 index_name 被覆盖
    from src.models import MarketIndexDaily
    row = db_session.query(MarketIndexDaily).filter_by(index_code="sh000001").first()
    assert row.index_name == "上证指数"


def test_insert_market_index_rows_skips_existing(db_session):
    rows = [_mk_index_row("sh000001")]
    df_mod.insert_market_index_rows(db_session, rows)
    n2 = df_mod.insert_market_index_rows(db_session, rows)
    assert n2 == 0


def test_fetch_and_store_today_orchestrates_sector_plus_4_indices(db_session):
    """fetch_and_store_today 应:1 次 sector 采集 + 4 次 index 采集,统计正确。"""
    sector_rows = [
        _mk_sector_row("BK0490", "半导体", 95.0, 0.0234),
        _mk_sector_row("BK0727", "5G概念", -150.0, -0.0300),
    ]
    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=sector_rows,
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ) as mock_idx:
        stats = df_mod.fetch_and_store_today(db_session)

    assert stats["sectors_fetched"] == 2
    assert stats["sectors_inserted"] == 2
    # 4 个市场指数都被调到
    assert mock_idx.call_count == 4
    assert stats["indices_fetched"] == 4
    assert stats["indices_inserted"] == 4
    assert stats["errors"] == []


def test_fetch_and_store_today_idempotent(db_session):
    """跑两次,第二次都跳过(已入库 = 不重复)。"""
    sector_rows = [_mk_sector_row("BK0490", "半导体", 95.0, 0.0234)]
    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=sector_rows,
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats1 = df_mod.fetch_and_store_today(db_session)
        stats2 = df_mod.fetch_and_store_today(db_session)

    assert stats1["sectors_inserted"] == 1
    assert stats1["indices_inserted"] == 4
    # 第二次完全跳过
    assert stats2["sectors_inserted"] == 0
    assert stats2["indices_inserted"] == 0


def test_fetch_and_store_today_continues_on_sector_fetch_failure(db_session):
    """sector fetch 抛 → 不影响 indices 采集。"""
    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        side_effect=RuntimeError("akshare timeout"),
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    assert stats["sectors_inserted"] == 0
    assert stats["indices_inserted"] == 4  # 仍跑了 4 个指数
    assert len(stats["errors"]) == 1
    assert "sector_flow_industry" in stats["errors"][0]


def test_fetch_and_store_today_continues_on_single_index_failure(db_session):
    """1 个指数失败 → 其他 3 个继续。"""
    sector_rows = [_mk_sector_row("BK0490", "半导体", 95.0, 0.0234)]

    def _index_side(code: str):
        if code == "sz399006":  # 创业板挂掉
            raise ConnectionError("network down")
        return [_mk_index_row(code)]

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=sector_rows,
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=_index_side,
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    assert stats["sectors_inserted"] == 1
    assert stats["indices_inserted"] == 3  # 4 - 1 失败 = 3
    assert len(stats["errors"]) == 1
    assert "sz399006" in stats["errors"][0]


def test_default_indices_list_size():
    """DEFAULT_INDICES 应该是 4 个(上证/深成/创业板/沪深300)。"""
    assert len(df_mod.DEFAULT_INDICES) == 4
    codes = [c for c, _ in df_mod.DEFAULT_INDICES]
    assert set(codes) == {"sh000001", "sz399001", "sz399006", "sh000300"}
