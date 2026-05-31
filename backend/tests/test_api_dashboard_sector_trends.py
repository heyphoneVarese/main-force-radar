"""GET /api/dashboard/sector-trends 测试(PR25)。

10 项 spec 覆盖:
 1. 空库返回 200 + items=[]
 2. >=20 天历史 → trend_20d 长度=20
 3. 历史不足 20 天 → trend_20d 长度等于实际天数
 4. trend_20d 按时间正序(oldest → newest)
 5. 不读 intraday_sector_flow(只插 intraday → 空)
 6. sector_type 过滤
 7. endpoint 返回 200
 8. 顺序跟 leaders 一致
 9. continuous_top20_days 等字段透传
10. latest_main_inflow_yi Decimal 正确
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from src.models import IntradaySectorFlow, SectorFlowDaily


def Y(yi: float) -> int:
    """亿元 → main_inflow_wan_x10000(× 1e8)。"""
    return int(yi * 100_000_000)


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
        main_inflow_wan_x10000=Y(inflow_yi),
        change_pct_x10000=100,
    )


def _seed_streak(
    db_session,
    code: str,
    name: str,
    *,
    days: int,
    base_end: date = date(2026, 5, 31),
    inflow_yi: float = 50.0,
    sector_type: str = "industry",
) -> None:
    for i in range(days):
        d = base_end - timedelta(days=i)
        db_session.add(_mk(code, name, d, inflow_yi, sector_type=sector_type))


# =====================================================================
# 1. 空库
# =====================================================================


def test_trends_empty_db(client):
    resp = client.get("/api/dashboard/sector-trends")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["sector_type"] == "industry"
    assert body["items"] == []


# =====================================================================
# 2. >=20 天 → trend_20d 长度 = 20
# =====================================================================


def test_trends_full_20_days(db_session, client):
    # seed 30 天 → 应该只取最近 20 天
    _seed_streak(db_session, "BK_A", "AA", days=30)
    db_session.commit()
    body = client.get("/api/dashboard/sector-trends").json()
    assert len(body["items"]) == 1
    assert len(body["items"][0]["trend_20d"]) == 20


# =====================================================================
# 3. 历史不足 20 天 → 返回实际天数
# =====================================================================


def test_trends_short_history_returns_partial(db_session, client):
    # 12 天历史
    _seed_streak(db_session, "BK_S", "Short", days=12)
    db_session.commit()
    body = client.get("/api/dashboard/sector-trends").json()
    assert len(body["items"]) == 1
    assert len(body["items"][0]["trend_20d"]) == 12


# =====================================================================
# 4. trend_20d 按时间正序(oldest → newest)
# =====================================================================


def test_trends_chronological_order(db_session, client):
    # 5 天数据,每天 inflow 是 (天数索引 + 1)亿,old = 1.0, new = 5.0
    base = date(2026, 5, 31)
    for i in range(5):
        # i=0 是最新日,inflow=5;i=4 是最旧,inflow=1
        d = base - timedelta(days=i)
        db_session.add(_mk("BK_T", "时序", d, 5.0 - i))
    db_session.commit()
    body = client.get("/api/dashboard/sector-trends").json()
    trend = [Decimal(v) for v in body["items"][0]["trend_20d"]]
    # 正序应是 1, 2, 3, 4, 5
    assert trend == [Decimal("1"), Decimal("2"), Decimal("3"),
                     Decimal("4"), Decimal("5")]


# =====================================================================
# 5. 不读 intraday
# =====================================================================


def test_trends_does_not_use_intraday(db_session, client):
    snap = datetime(2026, 5, 31, 14, 30)
    db_session.add(IntradaySectorFlow(
        sector_code="BK_I",
        sector_name="盘中独有",
        sector_type="industry",
        trade_date=snap.date(),
        snapshot_time=snap,
        main_inflow_wan_x10000=Y(999),
    ))
    db_session.commit()
    body = client.get("/api/dashboard/sector-trends").json()
    assert body["trade_date"] is None
    assert body["items"] == []


# =====================================================================
# 6. sector_type 过滤
# =====================================================================


def test_trends_sector_type_industry_only(db_session, client):
    _seed_streak(db_session, "BK_IND", "工业", days=10, sector_type="industry")
    _seed_streak(db_session, "BK_CON", "概念", days=10, sector_type="concept")
    db_session.commit()
    body = client.get(
        "/api/dashboard/sector-trends?sector_type=industry"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_IND"]


def test_trends_sector_type_concept_only(db_session, client):
    _seed_streak(db_session, "BK_IND", "工业", days=10, sector_type="industry")
    _seed_streak(db_session, "BK_CON", "概念", days=10, sector_type="concept")
    db_session.commit()
    body = client.get(
        "/api/dashboard/sector-trends?sector_type=concept"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_CON"]


def test_trends_sector_type_all(db_session, client):
    _seed_streak(db_session, "BK_IND", "工业", days=10, sector_type="industry")
    _seed_streak(db_session, "BK_CON", "概念", days=10, sector_type="concept")
    db_session.commit()
    body = client.get(
        "/api/dashboard/sector-trends?sector_type=all"
    ).json()
    codes = sorted(it["sector_code"] for it in body["items"])
    assert codes == ["BK_CON", "BK_IND"]


# =====================================================================
# 7. endpoint 返回 200(+ 参数校验)
# =====================================================================


def test_trends_endpoint_status_200(db_session, client):
    _seed_streak(db_session, "BK_A", "A", days=5)
    db_session.commit()
    assert client.get("/api/dashboard/sector-trends").status_code == 200


def test_trends_invalid_n_rejected(client):
    assert client.get("/api/dashboard/sector-trends?n=0").status_code == 422
    assert client.get("/api/dashboard/sector-trends?n=101").status_code == 422


def test_trends_invalid_sector_type_rejected(client):
    assert client.get(
        "/api/dashboard/sector-trends?sector_type=region"
    ).status_code == 422


# =====================================================================
# 8. 顺序跟 leaders 一致
# =====================================================================


def test_trends_order_matches_leaders(db_session, client):
    # 3 个板块,各 5 / 10 / 20 天连续 → leaders 排序应是 20 > 10 > 5
    _seed_streak(db_session, "BK_20", "L20", days=20)
    _seed_streak(db_session, "BK_10", "L10", days=10)
    _seed_streak(db_session, "BK_05", "L05", days=5)
    db_session.commit()
    trends = client.get("/api/dashboard/sector-trends").json()
    leaders = client.get(
        "/api/dashboard/sectors/persistence/leaders"
    ).json()
    trend_codes = [it["sector_code"] for it in trends["items"]]
    leader_codes = [it["sector_code"] for it in leaders["items"]]
    assert trend_codes == leader_codes


# =====================================================================
# 9. continuous_top20_days 等字段透传
# =====================================================================


def test_trends_persistence_fields_propagate(db_session, client):
    _seed_streak(db_session, "BK_A", "A", days=15)
    db_session.commit()
    body = client.get("/api/dashboard/sector-trends").json()
    it = body["items"][0]
    assert it["continuous_top20_days"] == 15
    # 15 天每天都流入(+50亿) → last_20_inflow_days 应该 = 15
    assert it["last_20_inflow_days"] == 15
    assert it["last_20_top20_days"] == 15


# =====================================================================
# 10. latest_main_inflow_yi Decimal 正确
# =====================================================================


def test_trends_latest_main_inflow_yi_decoded(db_session, client):
    base = date(2026, 5, 31)
    # 4 天历史,最新日 inflow=88.5 亿,其它日 30 亿
    for i in range(4):
        d = base - timedelta(days=i)
        v = 88.5 if i == 0 else 30.0
        db_session.add(_mk("BK_X", "X", d, v))
    db_session.commit()
    body = client.get("/api/dashboard/sector-trends").json()
    it = body["items"][0]
    assert Decimal(it["latest_main_inflow_yi"]) == Decimal("88.5")
    # trend 正序 → 最后一个就是最新日 88.5
    trend = [Decimal(v) for v in it["trend_20d"]]
    assert trend[-1] == Decimal("88.5")
    # 前面 3 天都是 30
    assert trend[0] == Decimal("30")
    assert trend[1] == Decimal("30")
    assert trend[2] == Decimal("30")
