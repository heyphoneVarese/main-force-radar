"""新增参数:
- GET /api/dashboard/sectors/top?order=inflow|outflow
- GET /api/dashboard/sectors/persistence/leaders?sort_by=...

只覆盖新增参数;不复测原有行为(其它测试文件已覆盖)。
"""

from __future__ import annotations

from datetime import date, timedelta

from src.models import SectorFlowDaily


def Y(yi: float) -> int:
    return int(yi * 100_000_000)


def _mk(code: str, name: str, d: date, inflow_yi: float,
        sector_type: str = "industry") -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=code, sector_name=name, sector_type=sector_type,
        trade_date=d, main_inflow_wan_x10000=Y(inflow_yi),
        change_pct_x10000=100,
    )


# =====================================================================
# /sectors/top?order=
# =====================================================================


def test_top_default_order_is_inflow_descending(db_session, client):
    d = date(2026, 6, 1)
    db_session.add_all([
        _mk("BK_A", "A", d, 100.0),
        _mk("BK_B", "B", d, -50.0),
        _mk("BK_C", "C", d, 30.0),
    ])
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/top?n=3&sector_type=industry"
    ).json()
    codes = [s["sector_code"] for s in body["sectors"]]
    assert codes == ["BK_A", "BK_C", "BK_B"]   # inflow DESC


def test_top_order_outflow_returns_most_negative_first(db_session, client):
    d = date(2026, 6, 1)
    db_session.add_all([
        _mk("BK_A", "A", d, 100.0),
        _mk("BK_B", "B", d, -50.0),
        _mk("BK_C", "C", d, -200.0),
        _mk("BK_D", "D", d, 30.0),
    ])
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/top?n=3&order=outflow"
    ).json()
    codes = [s["sector_code"] for s in body["sectors"]]
    # outflow:最负的(-200)排第 1
    assert codes == ["BK_C", "BK_B", "BK_D"]


def test_top_order_outflow_rank_is_one_based(db_session, client):
    d = date(2026, 6, 1)
    db_session.add_all([
        _mk("BK_X", "X", d, -100.0),
        _mk("BK_Y", "Y", d, -50.0),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/sectors/top?order=outflow").json()
    ranks = [s["rank"] for s in body["sectors"]]
    assert ranks == [1, 2]


def test_top_order_invalid_value_rejected(client):
    r = client.get("/api/dashboard/sectors/top?order=random")
    assert r.status_code == 422


# =====================================================================
# /sectors/persistence/leaders?sort_by=
# =====================================================================


def _seed_streak(db_session, code: str, *,
                 inflow_days: int, outflow_days: int = 0,
                 top20_days: int = 0,
                 base_end: date = date(2026, 6, 1)) -> None:
    """seed 一个板块的历史:从 base_end 倒数,前 inflow_days 天净流入,
    紧接着 outflow_days 天净流出。top20_days 通过单板块库自然满足
    (单板块永远 top1)。"""
    days = max(inflow_days + outflow_days, top20_days, 1)
    for i in range(days):
        d = base_end - timedelta(days=i)
        if i < outflow_days:
            v = -10.0
        elif i < outflow_days + inflow_days:
            v = 50.0
        else:
            v = 0.5
        db_session.add(_mk(code, code, d, v))


def test_leaders_sort_by_continuous_inflow(db_session, client):
    # BK_A: 连续流入 10 天;BK_B: 连续流入 3 天;BK_C: 连续流入 1 天
    _seed_streak(db_session, "BK_A", inflow_days=10)
    _seed_streak(db_session, "BK_B", inflow_days=3)
    _seed_streak(db_session, "BK_C", inflow_days=1)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders"
        "?sort_by=continuous_inflow&min_days=1"
    ).json()
    assert body["sort_by"] == "continuous_inflow"
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_A", "BK_B", "BK_C"]
    # 顶端的 continuous_inflow_days 必须是 10
    assert body["items"][0]["continuous_inflow_days"] == 10


def test_leaders_sort_by_continuous_outflow(db_session, client):
    # BK_X: 连续流出 5 天;BK_Y: 连续流出 2 天;BK_Z: 连续流出 0 天
    _seed_streak(db_session, "BK_X", inflow_days=0, outflow_days=5)
    _seed_streak(db_session, "BK_Y", inflow_days=0, outflow_days=2)
    _seed_streak(db_session, "BK_Z", inflow_days=1, outflow_days=0)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders"
        "?sort_by=continuous_outflow&min_days=1"
    ).json()
    assert body["sort_by"] == "continuous_outflow"
    codes = [it["sector_code"] for it in body["items"]]
    # BK_Z 连续流出 0 天 → 被 min_days=1 过滤掉
    assert codes == ["BK_X", "BK_Y"]
    assert body["items"][0]["continuous_outflow_days"] == 5


def test_leaders_default_sort_by_is_continuous_top20(db_session, client):
    _seed_streak(db_session, "BK_A", inflow_days=10)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?min_days=1"
    ).json()
    assert body["sort_by"] == "continuous_top20"


def test_leaders_sort_by_invalid_rejected(client):
    r = client.get(
        "/api/dashboard/sectors/persistence/leaders?sort_by=random_axis"
    )
    assert r.status_code == 422


def test_leaders_min_days_applies_to_chosen_axis(db_session, client):
    # BK_A: 连续流入 5 天;BK_B: 连续流入 2 天
    # sort_by=continuous_inflow + min_days=3 → 只留 BK_A
    _seed_streak(db_session, "BK_A", inflow_days=5)
    _seed_streak(db_session, "BK_B", inflow_days=2)
    db_session.commit()
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders"
        "?sort_by=continuous_inflow&min_days=3"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_A"]


def test_leaders_response_echoes_sort_by_for_empty_db(client):
    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?sort_by=continuous_outflow"
    ).json()
    assert body["trade_date"] is None
    assert body["sort_by"] == "continuous_outflow"
    assert body["items"] == []
