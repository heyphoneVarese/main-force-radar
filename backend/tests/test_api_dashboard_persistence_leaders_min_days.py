"""GET /api/dashboard/sectors/persistence/leaders 的 min_days 过滤(PR24)。

14 项 spec 覆盖:
 1. 默认 min_days=3 过滤掉 continuous_top20_days=1 的板块
 2. min_days=1 保留连续 1 天板块(兼容 PR22)
 3. min_days=10 只保留 >=10 天
 4. min_days=0 → 422
 5. min_days=61 → 422
 6. 排序逻辑不变
 7. response.min_days 回显请求值
 8. items 不足 n 时不补低于 min_days 的板块
 9. 空库仍 200 + min_days=请求值 + items=[]
10. sector_type=industry 正常
11. sector_type=concept 正常
12. sector_type=all 正常
13. 不影响 /api/dashboard/sectors/persistence
14. 不读 intraday_sector_flow
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.models import IntradaySectorFlow, SectorFlowDaily


def _mk(
    code: str,
    name: str,
    d: date,
    inflow_yi: float,
    sector_type: str = "industry",
) -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        trade_date=d,
        main_inflow_wan_x10000=int(inflow_yi * 100_000_000),
        change_pct_x10000=100,
    )


def _seed_streak(
    db_session,
    code: str,
    *,
    days: int,
    inflow_yi: float = 50.0,
    base_end: date = date(2026, 5, 31),
) -> None:
    """seed 一个板块连续 days 天 in top20(单板块库 → 它自然 top1)。"""
    for i in range(days):
        d = base_end - timedelta(days=i)
        db_session.add(_mk(code, code, d, inflow_yi))


# =====================================================================
# 1. 默认 min_days=3 过滤掉连续 1 天的
# =====================================================================


def test_min_days_default_filters_short_streak(db_session, client):
    _seed_streak(db_session, "BK_LONG", days=10)
    _seed_streak(db_session, "BK_SHORT", days=1)
    db_session.commit()
    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_LONG"]
    assert body["min_days"] == 3


# =====================================================================
# 2. min_days=1 保留所有
# =====================================================================


def test_min_days_1_keeps_all(db_session, client):
    _seed_streak(db_session, "BK_LONG", days=10)
    _seed_streak(db_session, "BK_SHORT", days=1)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?min_days=1"
    ).json()
    codes = {it["sector_code"] for it in body["items"]}
    assert codes == {"BK_LONG", "BK_SHORT"}
    assert body["min_days"] == 1


# =====================================================================
# 3. min_days=10 只保留 >=10
# =====================================================================


def test_min_days_10_keeps_only_long_streaks(db_session, client):
    _seed_streak(db_session, "BK_30", days=30)
    _seed_streak(db_session, "BK_10", days=10)
    _seed_streak(db_session, "BK_5", days=5)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?min_days=10"
    ).json()
    codes = {it["sector_code"] for it in body["items"]}
    assert codes == {"BK_30", "BK_10"}
    assert body["min_days"] == 10


# =====================================================================
# 4. min_days=0 → 422
# =====================================================================


def test_min_days_zero_rejected(client):
    r = client.get("/api/dashboard/sectors/persistence/leaders?min_days=0")
    assert r.status_code == 422


# =====================================================================
# 5. min_days=61 → 422
# =====================================================================


def test_min_days_too_large_rejected(client):
    r = client.get("/api/dashboard/sectors/persistence/leaders?min_days=61")
    assert r.status_code == 422


def test_min_days_negative_rejected(client):
    r = client.get("/api/dashboard/sectors/persistence/leaders?min_days=-1")
    assert r.status_code == 422


# =====================================================================
# 6. 排序逻辑不变(min_days 只过滤,不改顺序)
# =====================================================================


def test_min_days_preserves_sort_order(db_session, client):
    _seed_streak(db_session, "BK_30", days=30, inflow_yi=10.0)
    _seed_streak(db_session, "BK_15", days=15, inflow_yi=99.0)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?min_days=5"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    # continuous_top20 30 > 15 → 排序看连续天数,不看今日 inflow
    assert codes == ["BK_30", "BK_15"]


# =====================================================================
# 7. response.min_days 回显
# =====================================================================


def test_min_days_echoed_in_response(db_session, client):
    _seed_streak(db_session, "BK", days=5)
    db_session.commit()
    for v in [1, 3, 7, 60]:
        body = client.get(
            f"/api/dashboard/sectors/persistence/leaders?min_days={v}"
        ).json()
        assert body["min_days"] == v


# =====================================================================
# 8. 过滤后不足 n 不补
# =====================================================================


def test_min_days_under_n_does_not_pad(db_session, client):
    """3 个 >=3 天 + 5 个 <3 天;请求 n=10,min_days=3 → 只返 3 个。"""
    _seed_streak(db_session, "BK_LONG1", days=10)
    _seed_streak(db_session, "BK_LONG2", days=8)
    _seed_streak(db_session, "BK_LONG3", days=5)
    for i, code in enumerate(["BK_S1", "BK_S2", "BK_S3", "BK_S4", "BK_S5"]):
        _seed_streak(db_session, code, days=2, inflow_yi=1.0 + i)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?n=10&min_days=3"
    ).json()
    assert len(body["items"]) == 3
    codes = {it["sector_code"] for it in body["items"]}
    assert codes == {"BK_LONG1", "BK_LONG2", "BK_LONG3"}


# =====================================================================
# 9. 空库
# =====================================================================


def test_min_days_empty_db_returns_200(client):
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?min_days=5"
    ).json()
    assert body["trade_date"] is None
    assert body["min_days"] == 5
    assert body["items"] == []


# =====================================================================
# 10. sector_type=industry
# =====================================================================


def test_min_days_with_sector_type_industry(db_session, client):
    for i in range(5):
        d = date(2026, 5, 31) - timedelta(days=i)
        db_session.add(_mk("BK_IND", "ind", d, 50.0, sector_type="industry"))
        db_session.add(_mk("BK_CON", "con", d, 50.0, sector_type="concept"))
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders"
        "?sector_type=industry&min_days=3"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_IND"]


# =====================================================================
# 11. sector_type=concept
# =====================================================================


def test_min_days_with_sector_type_concept(db_session, client):
    for i in range(5):
        d = date(2026, 5, 31) - timedelta(days=i)
        db_session.add(_mk("BK_IND", "ind", d, 50.0, sector_type="industry"))
        db_session.add(_mk("BK_CON", "con", d, 50.0, sector_type="concept"))
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders"
        "?sector_type=concept&min_days=3"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_CON"]


# =====================================================================
# 12. sector_type=all
# =====================================================================


def test_min_days_with_sector_type_all(db_session, client):
    for i in range(5):
        d = date(2026, 5, 31) - timedelta(days=i)
        db_session.add(_mk("BK_IND", "ind", d, 50.0, sector_type="industry"))
        db_session.add(_mk("BK_CON", "con", d, 50.0, sector_type="concept"))
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders"
        "?sector_type=all&min_days=3"
    ).json()
    codes = sorted(it["sector_code"] for it in body["items"])
    assert codes == ["BK_CON", "BK_IND"]


# =====================================================================
# 13. 不影响 /sectors/persistence(PR20/21 端点)
# =====================================================================


def test_min_days_does_not_affect_persistence_endpoint(db_session, client):
    _seed_streak(db_session, "BK_LONG", days=10)
    _seed_streak(db_session, "BK_SHORT", days=1)
    db_session.commit()
    # /sectors/persistence 没有 min_days 概念,应该看到 2 个
    body = client.get("/api/dashboard/sectors/persistence").json()
    codes = {it["sector_code"] for it in body["items"]}
    assert codes == {"BK_LONG", "BK_SHORT"}


# =====================================================================
# 14. 不读 intraday
# =====================================================================


def test_min_days_does_not_use_intraday(db_session, client):
    snap = datetime(2026, 5, 31, 14, 30)
    db_session.add(IntradaySectorFlow(
        sector_code="BK_I",
        sector_name="盘中独有",
        sector_type="industry",
        trade_date=snap.date(),
        snapshot_time=snap,
        main_inflow_wan_x10000=99_999_999_999,
    ))
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?min_days=1"
    ).json()
    # 只有 intraday 数据,没 daily → 空
    assert body["trade_date"] is None
    assert body["items"] == []
