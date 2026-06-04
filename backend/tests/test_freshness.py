"""Freshness helper + fetcher 日志升级 + API freshness 字段(P0 fix)。"""

from __future__ import annotations

import logging
from datetime import date, datetime

import pytest

from src.models import (
    Fund,
    Holding,
    IntradaySectorFlow,
    MarketIndexDaily,
    SectorFlowDaily,
)
from src.services.freshness import (
    assess_daily_freshness,
    assess_intraday_freshness,
    assess_market_freshness,
)

# =====================================================================
# 辅助
# =====================================================================


def Y(yi: float) -> int:
    return int(yi * 100_000_000)


def _mk_intraday(snap: datetime, code: str = "BK_X") -> IntradaySectorFlow:
    return IntradaySectorFlow(
        sector_code=code,
        sector_name="测试",
        sector_type="industry",
        trade_date=snap.date(),
        snapshot_time=snap,
        main_inflow_wan_x10000=Y(10),
    )


def _mk_daily(d: date, code: str = "BK_X") -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=code,
        sector_name="测试",
        sector_type="industry",
        trade_date=d,
        main_inflow_wan_x10000=Y(10),
        change_pct_x10000=100,
    )


# =====================================================================
# intraday freshness helper
# =====================================================================


def test_intraday_freshness_empty_table(db_session):
    out = assess_intraday_freshness(
        db_session, now=datetime(2026, 6, 1, 14, 30)
    )
    assert out["is_fresh"] is False
    assert out["source"] == "intraday"
    assert out["latest_time"] is None
    assert "为空" in out["reason"]


def test_intraday_freshness_in_window_recent_is_fresh(db_session):
    # 模拟 now=14:30 (盘中),latest=14:25 → 5 分钟前
    now = datetime(2026, 6, 1, 14, 30)
    snap = datetime(2026, 6, 1, 14, 25)
    db_session.add(_mk_intraday(snap))
    db_session.commit()
    out = assess_intraday_freshness(db_session, now=now)
    assert out["is_fresh"] is True
    assert out["age_minutes"] == 5


def test_intraday_freshness_in_window_stale(db_session):
    # 盘中 14:30,但 latest 是 13:00 → 90 分钟前 → stale
    now = datetime(2026, 6, 1, 14, 30)
    snap = datetime(2026, 6, 1, 13, 0)
    db_session.add(_mk_intraday(snap))
    db_session.commit()
    out = assess_intraday_freshness(db_session, now=now)
    assert out["is_fresh"] is False
    assert out["age_minutes"] >= 15
    assert "分钟" in out["reason"]


def test_intraday_freshness_in_window_but_wrong_day(db_session):
    # 盘中 14:30,但 latest 是昨天 → stale
    now = datetime(2026, 6, 1, 14, 30)
    snap = datetime(2026, 5, 29, 14, 50)
    db_session.add(_mk_intraday(snap))
    db_session.commit()
    out = assess_intraday_freshness(db_session, now=now)
    assert out["is_fresh"] is False
    assert "不是今日" in out["reason"]


def test_intraday_freshness_after_close_today_ok(db_session):
    # 16:00 收盘后,latest 是今天 14:50 → fresh
    now = datetime(2026, 6, 1, 16, 0)
    snap = datetime(2026, 6, 1, 14, 50)
    db_session.add(_mk_intraday(snap))
    db_session.commit()
    out = assess_intraday_freshness(db_session, now=now)
    assert out["is_fresh"] is True


def test_intraday_freshness_weekend_recent_ok(db_session):
    # 周六 11:00,latest 是上周五 14:50 → fresh(节假日宽容)
    now = datetime(2026, 5, 30, 11, 0)   # 2026-05-30 = 周六
    snap = datetime(2026, 5, 29, 14, 50)
    db_session.add(_mk_intraday(snap))
    db_session.commit()
    out = assess_intraday_freshness(db_session, now=now)
    assert out["is_fresh"] is True


def test_intraday_freshness_too_old(db_session):
    # now 周六 11:00,latest 是 10 天前 → stale
    now = datetime(2026, 5, 30, 11, 0)
    snap = datetime(2026, 5, 20, 14, 50)
    db_session.add(_mk_intraday(snap))
    db_session.commit()
    out = assess_intraday_freshness(db_session, now=now)
    assert out["is_fresh"] is False
    # reason 可能是 "距今 X 天" 也可能是 "不是今日";只要 stale 即可
    assert out["latest_time"] is not None


# =====================================================================
# daily freshness helper
# =====================================================================


def test_daily_freshness_empty_table(db_session):
    out = assess_daily_freshness(
        db_session, now=datetime(2026, 6, 1, 16, 0)
    )
    assert out["is_fresh"] is False
    assert "为空" in out["reason"]


def test_daily_freshness_today_after_close_ok(db_session):
    now = datetime(2026, 6, 1, 16, 0)
    db_session.add(_mk_daily(date(2026, 6, 1)))
    db_session.commit()
    out = assess_daily_freshness(db_session, now=now)
    assert out["is_fresh"] is True


def test_daily_freshness_past_close_but_no_today(db_session):
    # P0 场景:周一 16:00 收盘后,daily 仍是上周五 → stale
    now = datetime(2026, 6, 1, 16, 0)   # 周一
    db_session.add(_mk_daily(date(2026, 5, 29)))   # 上周五
    db_session.commit()
    out = assess_daily_freshness(db_session, now=now)
    assert out["is_fresh"] is False
    assert "daily_fetch" in out["reason"]


def test_daily_freshness_pre_close_uses_last_trading_day(db_session):
    # 周一上午 10:00(尚未到 15:30),latest 是上周五 → fresh
    now = datetime(2026, 6, 1, 10, 0)
    db_session.add(_mk_daily(date(2026, 5, 29)))
    db_session.commit()
    out = assess_daily_freshness(db_session, now=now)
    assert out["is_fresh"] is True


def test_daily_freshness_too_old(db_session):
    now = datetime(2026, 6, 1, 16, 0)
    db_session.add(_mk_daily(date(2026, 5, 20)))   # 12 天前
    db_session.commit()
    out = assess_daily_freshness(db_session, now=now)
    assert out["is_fresh"] is False
    # reason 可能是 "daily_fetch 可能失败" 或 "距今 X 天";只要 stale 即可


# =====================================================================
# market freshness helper(复用 daily,只换 model)
# =====================================================================


def test_market_freshness_works(db_session):
    db_session.add(MarketIndexDaily(
        index_code="sh000001",
        index_name="上证综指",
        trade_date=date(2026, 6, 1),
        close_x10000=30_000_000,
        change_pct_x10000=100,
    ))
    db_session.commit()
    out = assess_market_freshness(
        db_session, now=datetime(2026, 6, 1, 16, 0)
    )
    assert out["is_fresh"] is True
    assert out["source"] == "market"


# =====================================================================
# fetcher 日志升级:inserted=0 + errors 必须打 ERROR
# =====================================================================


def test_data_fetcher_logs_error_when_inserted_zero_and_errors(
    db_session, monkeypatch, caplog
):
    """sector_flow / index 全部返空时 → ERROR 日志,而非 INFO 'success'。"""
    from src.services import data_fetcher

    def _empty_industry(*a, **kw):
        return []

    def _empty_index(*a, **kw):
        return []

    monkeypatch.setattr(data_fetcher, "fetch_sector_flow_industry", _empty_industry)
    monkeypatch.setattr(data_fetcher, "fetch_market_index", _empty_index)

    with caplog.at_level(logging.ERROR, logger=data_fetcher.logger.name):
        stats = data_fetcher.fetch_and_store_today(db_session)

    assert stats["sectors_inserted"] == 0
    assert stats["errors"], "errors 应非空(0 rows 已被自检捕获)"
    # 检查有 ERROR 级别的 fetch_and_store_today FAILED 日志
    error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("FAILED" in m and "inserted=0" in m for m in error_msgs), (
        f"未找到 ERROR 级别的失败日志;实际 ERROR 消息:{error_msgs}"
    )


def test_intraday_fetcher_logs_error_when_inserted_zero_and_errors(
    db_session, monkeypatch, caplog
):
    from src.services import intraday_fetcher

    # 让 _fetch_sector_flow_direct 抛错 → _with_retry 返 None → 触发 errors
    def _boom(*a, **kw):
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(intraday_fetcher, "_fetch_sector_flow_direct", _boom)

    with caplog.at_level(logging.ERROR, logger=intraday_fetcher.logger.name):
        stats = intraday_fetcher.fetch_and_store_intraday(
            db_session,
            snapshot_time=datetime(2026, 6, 1, 14, 30),
        )

    assert stats["inserted"] == 0
    assert stats["errors"], "errors 应非空"
    error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("FAILED" in m and "inserted=0" in m for m in error_msgs), (
        f"未找到 ERROR 级别的失败日志;实际 ERROR 消息:{error_msgs}"
    )


# =====================================================================
# API 集成:8 个 endpoint 都返回 freshness 字段
# =====================================================================


@pytest.fixture
def _seed_minimal(db_session):
    """灌一点点 daily + intraday + holdings,让端点都有可序列化输出。"""
    db_session.add(_mk_daily(date(2026, 5, 31), code="BK_A"))
    db_session.add(_mk_intraday(datetime(2026, 5, 31, 14, 30), code="BK_A"))
    db_session.add(Fund(
        fund_code="F01", fund_name="测试基金", fund_type="其他",
        related_sectors=["测试"],
    ))
    db_session.add(Holding(
        fund_code="F01", cost_nav_x10000=10000, shares_x100=1_000_000,
        bought_at=date(2025, 1, 1),
    ))
    db_session.commit()


_ENDPOINTS_WITH_FRESHNESS = [
    "/api/dashboard/market",
    "/api/dashboard/sectors/top",
    "/api/dashboard/sectors/persistence",
    "/api/dashboard/sectors/persistence/leaders",
    "/api/dashboard/sector-trends",
    "/api/dashboard/intraday/sectors/top",
    "/api/dashboard/holding-sector-alerts",
    "/api/dashboard/holdings-facts",
    "/api/dashboard/capital-migration",
    "/api/dashboard/holdings/capital-migration",
    "/api/dashboard/funds/top",
    "/api/dashboard/radar",
    "/api/dashboard/ai-summary",
]


@pytest.mark.parametrize("path", _ENDPOINTS_WITH_FRESHNESS)
def test_endpoint_includes_freshness_field(_seed_minimal, client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "freshness" in body, f"{path} 缺 freshness 字段"
    f = body["freshness"]
    assert isinstance(f["is_fresh"], bool)
    assert f["source"] in ("intraday", "daily", "market")
    assert f["source_type"] in ("intraday", "daily_close", "cached", "stale")
    assert "data_date" in f
    assert "data_time" in f
    assert "updated_at" in f
    assert isinstance(f["reason"], str) and len(f["reason"]) > 0
    assert "time_meta" in body, f"{path} 缺 time_meta 字段"
    tm = body["time_meta"]
    assert tm["source_type"] in ("intraday", "daily_close", "cached", "stale")
    assert isinstance(tm["is_fresh"], bool)
    assert "data_date" in tm
    assert "data_time" in tm
    assert "updated_at" in tm


def test_endpoint_freshness_marks_stale_when_old_data(db_session, client):
    """灌很旧的数据 → freshness.is_fresh 应该 False。"""
    db_session.add(_mk_daily(date(2025, 1, 1)))   # ~ 17 个月前
    db_session.commit()
    body = client.get("/api/dashboard/sectors/top").json()
    assert body["freshness"]["is_fresh"] is False
    assert body["freshness"]["latest_time"] is not None


def test_fetch_health_endpoint_shape(client):
    body = client.get("/api/dashboard/fetch-health").json()
    assert body["status"] in {"never_run", "ok", "partial_failure", "failed"}
    assert isinstance(body["ok"], bool)
    assert isinstance(body["errors"], list)
    assert "last_run_at" in body
    assert "stats" in body
