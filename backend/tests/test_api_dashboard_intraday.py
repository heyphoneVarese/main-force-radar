"""GET /api/dashboard/intraday/sectors/top 测试(PR15)。

跟 test_api_dashboard.py 的 daily sectors/top 用例平行,
重点验证 snapshot_time 隔离(只返最新 snapshot 那批)。
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.models import IntradaySectorFlow


def _mk(
    code: str,
    name: str,
    sector_type: str,
    snapshot_time: datetime,
    main_inflow_wan_x10000: int,
    main_inflow_pct_x10000: int | None = None,
    change_pct_x10000: int | None = None,
) -> IntradaySectorFlow:
    return IntradaySectorFlow(
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        trade_date=snapshot_time.date(),
        snapshot_time=snapshot_time,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        main_inflow_pct_x10000=main_inflow_pct_x10000,
        change_pct_x10000=change_pct_x10000,
    )


# ============================================================
# 空库
# ============================================================


def test_intraday_empty_db_returns_nulls(client):
    resp = client.get("/api/dashboard/intraday/sectors/top")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["snapshot_time"] is None
    assert body["sector_type"] == "industry"
    assert body["sectors"] == []


# ============================================================
# 多 snapshot:只返最新
# ============================================================


def test_intraday_returns_only_latest_snapshot(db_session, client):
    s_old = datetime(2026, 6, 1, 9, 35)
    s_new = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk("BK0727", "半导体", "industry", s_old, 9_999_999_999),
        _mk("BK0727", "半导体", "industry", s_new, 12_000_000_000),
        _mk("BK0428", "电池", "industry", s_new, 5_200_000_000),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/intraday/sectors/top").json()
    # snapshot_time 应该是 14:30 那个,只列 2 个板块(半导体 + 电池),不混 old
    assert "2026-06-01T14:30" in body["snapshot_time"]
    codes = [s["sector_code"] for s in body["sectors"]]
    assert codes == ["BK0727", "BK0428"]
    # 半导体的 main_inflow 应该是 new 那条(120 亿)而非 old
    semi = body["sectors"][0]
    assert Decimal(semi["main_inflow_wan"]) == Decimal("1200000")


# ============================================================
# sector_type 过滤
# ============================================================


@pytest.fixture
def seed_mixed_one_snapshot(db_session):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk("BK0727", "半导体", "industry", s, 12_000_000_000, 920, 312),
        _mk("BK0428", "电池", "industry", s, 5_200_000_000, 830, 234),
        _mk("BK0429", "光伏设备", "industry", s, -1_800_000_000, -310, -150),
        _mk("BK0739", "AI算力", "concept", s, 8_800_000_000, 700, 280),
        _mk("BK0888", "数字货币", "concept", s, 500_000_000, 200, 90),
    ])
    db_session.commit()
    return s


def test_intraday_industry_filter(client, seed_mixed_one_snapshot):
    body = client.get(
        "/api/dashboard/intraday/sectors/top?sector_type=industry"
    ).json()
    codes = [s["sector_code"] for s in body["sectors"]]
    assert codes == ["BK0727", "BK0428", "BK0429"]  # 降序


def test_intraday_concept_filter(client, seed_mixed_one_snapshot):
    body = client.get(
        "/api/dashboard/intraday/sectors/top?sector_type=concept"
    ).json()
    codes = [s["sector_code"] for s in body["sectors"]]
    assert codes == ["BK0739", "BK0888"]
    assert all(s["sector_type"] == "concept" for s in body["sectors"])


def test_intraday_all_filter_mixes_types(client, seed_mixed_one_snapshot):
    body = client.get(
        "/api/dashboard/intraday/sectors/top?sector_type=all"
    ).json()
    assert len(body["sectors"]) == 5
    # 降序:半导体(120) > AI算力(88) > 电池(52) > 数字货币(5) > 光伏(-18)
    codes = [s["sector_code"] for s in body["sectors"]]
    assert codes == ["BK0727", "BK0739", "BK0428", "BK0888", "BK0429"]


# ============================================================
# n 参数 + Decimal decode
# ============================================================


def test_intraday_n_param_limits(client, seed_mixed_one_snapshot):
    body = client.get(
        "/api/dashboard/intraday/sectors/top?sector_type=all&n=2"
    ).json()
    assert len(body["sectors"]) == 2
    assert [s["rank"] for s in body["sectors"]] == [1, 2]


def test_intraday_decimal_decode(client, seed_mixed_one_snapshot):
    body = client.get(
        "/api/dashboard/intraday/sectors/top?n=1"
    ).json()
    s = body["sectors"][0]
    # main_inflow_wan_x10000 = 12_000_000_000 → / 10000 = 1_200_000 万元
    assert Decimal(s["main_inflow_wan"]) == Decimal("1200000")
    assert Decimal(s["main_inflow_pct"]) == Decimal("0.092")
    assert Decimal(s["change_pct"]) == Decimal("0.0312")


def test_intraday_null_pct_fields_preserved(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk(
        "BK_NULL", "测试板块", "industry", s,
        main_inflow_wan_x10000=1_000_000_000,
        main_inflow_pct_x10000=None,
        change_pct_x10000=None,
    ))
    db_session.commit()

    body = client.get(
        "/api/dashboard/intraday/sectors/top"
    ).json()
    assert body["sectors"][0]["main_inflow_pct"] is None
    assert body["sectors"][0]["change_pct"] is None


# ============================================================
# 参数校验
# ============================================================


def test_intraday_invalid_n_rejected(client):
    assert client.get(
        "/api/dashboard/intraday/sectors/top?n=0"
    ).status_code == 422
    assert client.get(
        "/api/dashboard/intraday/sectors/top?n=101"
    ).status_code == 422


def test_intraday_invalid_sector_type_rejected(client):
    assert client.get(
        "/api/dashboard/intraday/sectors/top?sector_type=region"
    ).status_code == 422
    assert client.get(
        "/api/dashboard/intraday/sectors/top?sector_type=bogus"
    ).status_code == 422


# ============================================================
# trade_date 字段
# ============================================================


def test_intraday_trade_date_derived_from_snapshot(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk(
        "BK0727", "半导体", "industry", s, 12_000_000_000
    ))
    db_session.commit()

    body = client.get("/api/dashboard/intraday/sectors/top").json()
    assert body["trade_date"] == "2026-06-01"


# ============================================================
# 不影响 daily 端点
# ============================================================


def test_intraday_endpoint_does_not_affect_daily(db_session, client):
    """快速验证:写 intraday 不影响 /sectors/top(daily)返空。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk(
        "BK0727", "半导体", "industry", s, 12_000_000_000
    ))
    db_session.commit()

    daily = client.get("/api/dashboard/sectors/top").json()
    assert daily["trade_date"] is None   # sector_flow_daily 表仍空
    assert daily["sectors"] == []
