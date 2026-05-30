"""intraday_fetcher 单测(PR15)— mock _fetch_sector_flow_direct,断言
行解析、入库、UniqueConstraint 幂等。
"""

from datetime import datetime, time
from unittest.mock import patch

import pandas as pd
import pytest

from src.models import IntradaySectorFlow
from src.services import intraday_fetcher as mod


# ============================================================
# is_in_trading_window
# ============================================================


@pytest.mark.parametrize("now_t,expected", [
    (time(8, 50), False),      # 集合竞价前
    (time(9, 25), False),      # 集合竞价中
    (time(9, 34), False),      # 9:35 前 1 分钟
    (time(9, 35), True),       # 上午开盘第 1 个采集点
    (time(10, 30), True),      # 上午中段
    (time(11, 30), True),      # 上午收盘
    (time(11, 31), False),     # 午休
    (time(12, 0), False),      # 午休
    (time(12, 59), False),     # 下午开盘前
    (time(13, 0), True),       # 下午开盘
    (time(14, 55), True),      # 下午尾盘
    (time(14, 56), False),     # 14:55 后 1 分钟,daily_fetch 接力
    (time(15, 0), False),      # 收盘
])
def test_is_in_trading_window(now_t, expected):
    dt = datetime(2026, 6, 1, now_t.hour, now_t.minute)
    assert mod.is_in_trading_window(dt) is expected


# ============================================================
# fixtures
# ============================================================


@pytest.fixture
def fake_industry_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "名称": "半导体",
            "代码": "BK0727",
            "今日涨跌幅": 3.12,
            "今日主力净流入-净额": 12_000_000_000.0,   # 120 亿元
            "今日主力净流入-净占比": 9.2,
        },
        {
            "名称": "电池",
            "代码": "BK0428",
            "今日涨跌幅": 2.34,
            "今日主力净流入-净额": 5_200_000_000.0,    # 52 亿元
            "今日主力净流入-净占比": 8.3,
        },
        {
            "名称": "光伏设备",
            "代码": "BK0429",
            "今日涨跌幅": -1.5,
            "今日主力净流入-净额": -1_800_000_000.0,   # -18 亿元
            "今日主力净流入-净占比": -3.1,
        },
    ])


@pytest.fixture
def fake_concept_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "名称": "AI算力",
            "代码": "BK0739",
            "今日涨跌幅": 2.8,
            "今日主力净流入-净额": 8_800_000_000.0,
            "今日主力净流入-净占比": 7.0,
        },
    ])


# ============================================================
# _df_to_intraday_rows
# ============================================================


def test_df_to_rows_maps_5_fields(fake_industry_df):
    snapshot = datetime(2026, 6, 1, 14, 30)
    rows = mod._df_to_intraday_rows(
        fake_industry_df, db_sector_type="industry", snapshot_time=snapshot
    )
    assert len(rows) == 3
    r0 = rows[0]
    # 半导体:120 亿 = 12_000_000 万 × 10000 = 1.2e10
    assert r0["main_inflow_wan_x10000"] == 12_000_000_000
    # 9.2% / 100 = 0.092 × 10000 = 920
    assert r0["main_inflow_pct_x10000"] == 920
    # 3.12% / 100 = 0.0312 × 10000 = 312
    assert r0["change_pct_x10000"] == 312
    assert r0["sector_type"] == "industry"
    assert r0["trade_date"] == snapshot.date()
    assert r0["snapshot_time"] == snapshot


def test_df_to_rows_handles_negative_inflow(fake_industry_df):
    snapshot = datetime(2026, 6, 1, 14, 30)
    rows = mod._df_to_intraday_rows(
        fake_industry_df, db_sector_type="industry", snapshot_time=snapshot
    )
    # 光伏 fixture: -1.8e9 元 = -18 亿元 = -180,000 万元
    # wan_yuan_to_int(-180_000) = -180_000 × 10_000 = -1_800_000_000
    pv = next(r for r in rows if r["sector_code"] == "BK0429")
    assert pv["main_inflow_wan_x10000"] == -1_800_000_000
    assert pv["change_pct_x10000"] == -150


def test_df_to_rows_skips_row_with_missing_inflow():
    df = pd.DataFrame([
        {"名称": "电池", "代码": "BK0428", "今日涨跌幅": 2.0,
         "今日主力净流入-净额": None, "今日主力净流入-净占比": 5.0},
        {"名称": "半导体", "代码": "BK0727", "今日涨跌幅": 3.0,
         "今日主力净流入-净额": 1_000_000.0, "今日主力净流入-净占比": 6.0},
    ])
    rows = mod._df_to_intraday_rows(
        df, db_sector_type="industry",
        snapshot_time=datetime(2026, 6, 1, 14, 30),
    )
    assert len(rows) == 1
    assert rows[0]["sector_code"] == "BK0727"


def test_df_to_rows_empty_df_returns_empty():
    rows = mod._df_to_intraday_rows(
        pd.DataFrame(), db_sector_type="industry",
        snapshot_time=datetime(2026, 6, 1, 14, 30),
    )
    assert rows == []


# ============================================================
# fetch_and_store_intraday
# ============================================================


def test_fetch_and_store_intraday_inserts_both_types(
    db_session, fake_industry_df, fake_concept_df
):
    snapshot = datetime(2026, 6, 1, 14, 30)

    def _direct(ak_type):
        return fake_industry_df if ak_type == "行业资金流" else fake_concept_df

    with patch(
        "src.services.intraday_fetcher._fetch_sector_flow_direct",
        side_effect=_direct,
    ):
        stats = mod.fetch_and_store_intraday(
            db_session, snapshot_time=snapshot
        )

    assert stats["snapshot_time"] == snapshot
    assert stats["inserted"] == 4  # 3 industry + 1 concept
    assert stats["skipped"] == 0
    assert stats["by_type"]["industry"]["inserted"] == 3
    assert stats["by_type"]["concept"]["inserted"] == 1
    assert stats["errors"] == []

    # DB 行确实存了
    cnt = db_session.query(IntradaySectorFlow).count()
    assert cnt == 4


def test_fetch_and_store_intraday_truncates_seconds(
    db_session, fake_industry_df
):
    """snapshot_time 入库前抹掉 second/microsecond,保证 UniqueConstraint
    在同一分钟内幂等。"""
    sloppy = datetime(2026, 6, 1, 14, 30, 47, 123456)
    with patch(
        "src.services.intraday_fetcher._fetch_sector_flow_direct",
        return_value=fake_industry_df,
    ):
        stats = mod.fetch_and_store_intraday(
            db_session,
            sector_types=("industry",),
            snapshot_time=sloppy,
        )
    assert stats["snapshot_time"].second == 0
    assert stats["snapshot_time"].microsecond == 0
    row = db_session.query(IntradaySectorFlow).first()
    assert row.snapshot_time.second == 0
    assert row.snapshot_time.microsecond == 0


def test_fetch_and_store_intraday_idempotent_same_snapshot(
    db_session, fake_industry_df
):
    """同一 snapshot_time + sector_code 二次采集 → skip,DB 行数不变。"""
    snapshot = datetime(2026, 6, 1, 14, 30)

    with patch(
        "src.services.intraday_fetcher._fetch_sector_flow_direct",
        return_value=fake_industry_df,
    ):
        stats1 = mod.fetch_and_store_intraday(
            db_session,
            sector_types=("industry",),
            snapshot_time=snapshot,
        )
        stats2 = mod.fetch_and_store_intraday(
            db_session,
            sector_types=("industry",),
            snapshot_time=snapshot,
        )

    assert stats1["inserted"] == 3
    assert stats2["inserted"] == 0
    assert stats2["skipped"] == 3
    assert db_session.query(IntradaySectorFlow).count() == 3


def test_fetch_and_store_intraday_different_snapshots_both_kept(
    db_session, fake_industry_df
):
    """不同 snapshot_time → 各自入库,DB 累计行数。"""
    s1 = datetime(2026, 6, 1, 14, 30)
    s2 = datetime(2026, 6, 1, 14, 40)

    with patch(
        "src.services.intraday_fetcher._fetch_sector_flow_direct",
        return_value=fake_industry_df,
    ):
        mod.fetch_and_store_intraday(
            db_session, sector_types=("industry",), snapshot_time=s1
        )
        mod.fetch_and_store_intraday(
            db_session, sector_types=("industry",), snapshot_time=s2
        )

    assert db_session.query(IntradaySectorFlow).count() == 6


def test_fetch_and_store_intraday_records_fetch_error(db_session, monkeypatch):
    """data_fetcher 抛 → _with_retry 失败回 None → errors 记一条,
    不抛给上层。"""
    monkeypatch.setattr(mod, "_with_retry", lambda *_a, **_k: None)
    stats = mod.fetch_and_store_intraday(
        db_session,
        sector_types=("industry",),
        snapshot_time=datetime(2026, 6, 1, 14, 30),
    )
    assert stats["inserted"] == 0
    assert any("industry" in e for e in stats["errors"])


def test_fetch_and_store_intraday_partial_failure_continues(
    db_session, fake_industry_df, monkeypatch
):
    """industry 成,concept 失败 → industry 行入库,concept 记 error。"""
    def _direct(ak_type):
        if ak_type == "概念资金流":
            raise ConnectionError("concept down")
        return fake_industry_df

    # _with_retry 会捕获并 retry,失败返 None。我们直接 patch _with_retry 看
    # call-by-call 决定结果。
    def _retry_stub(label, fn, fallback):
        try:
            return fn()
        except Exception:
            return fallback

    monkeypatch.setattr(mod, "_with_retry", _retry_stub)

    with patch(
        "src.services.intraday_fetcher._fetch_sector_flow_direct",
        side_effect=_direct,
    ):
        stats = mod.fetch_and_store_intraday(
            db_session,
            sector_types=("industry", "concept"),
            snapshot_time=datetime(2026, 6, 1, 14, 30),
        )

    assert stats["inserted"] == 3  # industry
    assert stats["by_type"]["industry"]["inserted"] == 3
    assert any("concept" in e for e in stats["errors"])
