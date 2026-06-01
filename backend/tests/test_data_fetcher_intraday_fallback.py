"""fetch_and_store_today 的 P0 intraday fallback。

场景:VPS 上 direct industry + akshare 都拿不到 daily,但 intraday 已经
拿到了今天 14:30 的 686 行;让 daily 不再卡在昨天 — 用 intraday 当日
latest snapshot 的 industry 行作为 sector_flow_daily 的源。

只 industry,不 concept;intraday 不是今天则放弃;market_index_daily
完全不受影响。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.models import IntradaySectorFlow, SectorFlowDaily
from src.services import data_fetcher as df_mod
from src.utils.date_helper import cn_today


def Y(yi: float) -> int:
    return int(yi * 100_000_000)


def _mk_intraday(
    snap: datetime,
    code: str,
    name: str = "测试",
    inflow_yi: float = 50.0,
    sector_type: str = "industry",
) -> IntradaySectorFlow:
    return IntradaySectorFlow(
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        trade_date=snap.date(),
        snapshot_time=snap,
        main_inflow_wan_x10000=Y(inflow_yi),
        main_inflow_pct_x10000=None,
        change_pct_x10000=int(0.02 * 10_000),
    )


def _mk_index_row(code: str):
    return {
        "index_code": code,
        "index_name": code,
        "trade_date": cn_today(),
        "close_x10000": 41129000,
        "change_pct_x10000": 87,
        "turnover_wan_x10000": None,
    }


# =====================================================================
# 1. direct daily 成功 → 不进 fallback
# =====================================================================


def test_direct_success_does_not_use_fallback(db_session):
    sector_rows = [
        {
            "trade_date": cn_today(),
            "sector_code": "BK0490",
            "sector_name": "半导体",
            "sector_type": "industry",
            "main_inflow_wan_x10000": Y(95.0),
            "main_inflow_pct_x10000": None,
            "change_pct_x10000": 234,
        }
    ]
    # 同时也灌一条今日 intraday(确保 fallback 路径 *可用* 但不被触发)
    today = cn_today()
    snap = datetime(today.year, today.month, today.day, 14, 30)
    db_session.add(_mk_intraday(snap, "BK_INTRADAY", inflow_yi=10.0))
    db_session.commit()

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=sector_rows,
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    assert stats["sectors_fetched"] == 1
    assert stats["sectors_inserted"] == 1
    assert "fallback_used" not in stats, (
        "direct 成功时 fallback_used 不该出现"
    )
    # 入库的应该是 BK0490(direct),不是 BK_INTRADAY
    today_rows = db_session.query(SectorFlowDaily).filter_by(
        trade_date=cn_today(), sector_type="industry"
    ).all()
    codes = sorted(r.sector_code for r in today_rows)
    assert codes == ["BK0490"], f"期望只有 direct 的 BK0490,实际:{codes}"


# =====================================================================
# 2. direct daily 失败 + intraday 有今天数据 → fallback 成功写入
# =====================================================================


def test_direct_fail_intraday_today_triggers_fallback(db_session):
    today = cn_today()
    snap = datetime(today.year, today.month, today.day, 14, 30)
    # 今日 intraday 有 3 行 industry + 2 行 concept(只有 industry 应该被复制)
    db_session.add_all([
        _mk_intraday(snap, "BK0490", "半导体", 95.0, "industry"),
        _mk_intraday(snap, "BK0727", "光模块", 40.0, "industry"),
        _mk_intraday(snap, "BK0428", "电池",   -10.0, "industry"),
        _mk_intraday(snap, "BK9001", "CPO",    50.0, "concept"),
        _mk_intraday(snap, "BK9002", "AI",     30.0, "concept"),
    ])
    db_session.commit()

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=[],  # direct + akshare 都拿不到
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    assert stats["sectors_fetched"] == 3, "fallback 应该用了 3 行 industry"
    assert stats["sectors_inserted"] == 3
    assert stats.get("fallback_used") == "intraday_snapshot"
    assert stats["errors"] == [], (
        f"fallback 成功后不该再有 sector errors;实际:{stats['errors']}"
    )
    # 入库的 trade_date 应该是今天,只有 industry
    today_rows = db_session.query(SectorFlowDaily).filter_by(
        trade_date=today
    ).all()
    assert len(today_rows) == 3
    assert all(r.sector_type == "industry" for r in today_rows), (
        "spec 红线:fallback 不许写 concept"
    )
    codes = sorted(r.sector_code for r in today_rows)
    assert codes == ["BK0428", "BK0490", "BK0727"]
    # market 指数不受影响
    assert stats["indices_inserted"] == 4


# =====================================================================
# 3. direct daily 失败 + intraday 没今天数据 → errors 非空
# =====================================================================


def test_direct_fail_no_today_intraday_returns_error(db_session):
    # 灌一条"昨天"的 intraday,fallback 应该跳过
    yesterday = cn_today() - timedelta(days=1)
    snap_yesterday = datetime(
        yesterday.year, yesterday.month, yesterday.day, 14, 30
    )
    db_session.add(_mk_intraday(snap_yesterday, "BK_OLD", inflow_yi=50.0))
    db_session.commit()

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=[],
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    assert stats["sectors_fetched"] == 0
    assert stats["sectors_inserted"] == 0
    assert "fallback_used" not in stats
    assert len(stats["errors"]) == 1
    msg = stats["errors"][0]
    assert "sector_flow_industry" in msg
    assert "0 rows" in msg  # 跟旧契约一致(test_data_fetcher 老测试也查这个)
    assert "intraday fallback also empty/wrong-day" in msg
    # market 不受影响
    assert stats["indices_inserted"] == 4
    # 不该把昨天的 intraday 写到今天的 daily
    today_rows = db_session.query(SectorFlowDaily).filter_by(
        trade_date=cn_today()
    ).all()
    assert today_rows == []


# =====================================================================
# 4. direct fetcher 抛异常 + intraday 有今天数据 → fallback 兜底
# =====================================================================


def test_direct_raises_with_today_intraday_uses_fallback(db_session):
    today = cn_today()
    snap = datetime(today.year, today.month, today.day, 14, 30)
    db_session.add(_mk_intraday(snap, "BK0490", "半导体", 95.0))
    db_session.commit()

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        side_effect=RuntimeError("ConnectionError simulated"),
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    # 异常路径仍可被 fallback 救回来
    assert stats["sectors_inserted"] == 1
    assert stats.get("fallback_used") == "intraday_snapshot"
    assert stats["errors"] == []
    assert stats["indices_inserted"] == 4


# =====================================================================
# 5. intraday 空表 → 同样 errors 非空(不崩)
# =====================================================================


def test_direct_fail_empty_intraday_table_returns_error(db_session):
    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=[],
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    assert stats["sectors_inserted"] == 0
    assert "fallback_used" not in stats
    assert any("sector_flow_industry" in e for e in stats["errors"])


# =====================================================================
# 6. fallback 只挑 industry,即使 intraday 有 concept 也忽略
# =====================================================================


def test_fallback_only_industry_never_concept(db_session):
    today = cn_today()
    snap = datetime(today.year, today.month, today.day, 14, 30)
    db_session.add_all([
        _mk_intraday(snap, "BK_C1", "CPO", 100.0, "concept"),
        _mk_intraday(snap, "BK_C2", "AI",  80.0, "concept"),
    ])
    db_session.commit()

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=[],
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    # 没有 industry 行可用 → 不进入 fallback 命中分支
    assert stats["sectors_inserted"] == 0
    assert "fallback_used" not in stats
    today_rows = db_session.query(SectorFlowDaily).filter_by(
        trade_date=today
    ).all()
    assert today_rows == []
    # concept 行不该被乱写
    concept_rows = db_session.query(SectorFlowDaily).filter_by(
        sector_type="concept"
    ).all()
    assert concept_rows == []


# =====================================================================
# 7. fallback 入库幂等(同日重跑 → skip)
# =====================================================================


def test_fallback_insert_is_idempotent(db_session):
    today = cn_today()
    snap = datetime(today.year, today.month, today.day, 14, 30)
    db_session.add(_mk_intraday(snap, "BK0490", "半导体", 95.0))
    db_session.commit()

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=[],
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        s1 = df_mod.fetch_and_store_today(db_session)
        s2 = df_mod.fetch_and_store_today(db_session)

    assert s1["sectors_inserted"] == 1
    assert s2["sectors_inserted"] == 0  # 同 (trade_date, sector_code) 跳过
    # 但两次都标记了 fallback_used
    assert s1.get("fallback_used") == "intraday_snapshot"
    assert s2.get("fallback_used") == "intraday_snapshot"


# =====================================================================
# 8. market_index_daily 不受 fallback 影响(独立链路)
# =====================================================================


def test_fallback_does_not_affect_market_index(db_session):
    today = cn_today()
    snap = datetime(today.year, today.month, today.day, 14, 30)
    db_session.add(_mk_intraday(snap, "BK0490", "半导体", 95.0))
    db_session.commit()

    with patch(
        "src.services.data_fetcher.fetch_sector_flow_industry",
        return_value=[],
    ), patch(
        "src.services.data_fetcher.fetch_market_index",
        side_effect=lambda code: [_mk_index_row(code)],
    ):
        stats = df_mod.fetch_and_store_today(db_session)

    # 指数 4 个全进
    from src.models import MarketIndexDaily
    n_index = db_session.query(MarketIndexDaily).filter_by(
        trade_date=today
    ).count()
    assert n_index == 4
    assert stats["indices_fetched"] == 4
    assert stats["indices_inserted"] == 4
