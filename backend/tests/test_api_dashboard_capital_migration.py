"""Phase 6 V1 资金迁移雷达 API 测试。

覆盖:
- 空库
- 不足 20 日
- 弱转强
- 强转弱
- verified 持仓映射参与
- low_confidence 不参与判断
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.models import Fund, Holding, SectorAlias, SectorFlowDaily


def Y(yi: int) -> int:
    """亿元 → main_inflow_wan_x10000。"""
    return yi * 100_000_000


def _flow(
    *,
    code: str,
    name: str,
    trade_date: date,
    yi: int,
    sector_type: str = "industry",
) -> SectorFlowDaily:
    return SectorFlowDaily(
        trade_date=trade_date,
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        main_inflow_wan_x10000=Y(yi),
        change_pct_x10000=100,
    )


def _seed_series(
    db_session,
    *,
    code: str,
    name: str,
    values: list[int],
    end: date = date(2026, 6, 3),
    sector_type: str = "industry",
) -> None:
    start = end - timedelta(days=len(values) - 1)
    for i, yi in enumerate(values):
        db_session.add(_flow(
            code=code,
            name=name,
            trade_date=start + timedelta(days=i),
            yi=yi,
            sector_type=sector_type,
        ))


def _fund(
    code: str,
    name: str,
    labels: list[str],
) -> Fund:
    return Fund(
        fund_code=code,
        fund_name=name,
        fund_type="股票型",
        related_sectors=labels,
    )


def _holding(code: str) -> Holding:
    return Holding(
        fund_code=code,
        cost_nav_x10000=10000,
        shares_x100=10000,
        bought_at=date(2026, 5, 1),
    )


def test_capital_migration_empty_db(client):
    body = client.get("/api/dashboard/capital-migration").json()

    assert body["trade_date"] is None
    assert body["sample_days"] == 0
    assert body["inflowing"] == []
    assert body["outflowing"] == []
    assert body["weak_to_strong"] == []
    assert body["strong_to_weak"] == []
    assert "freshness" in body


def test_capital_migration_short_history_marks_partial(db_session, client):
    _seed_series(
        db_session,
        code="BK_SHORT",
        name="短样本",
        values=[-2, -1, 1, 2, 3],
    )
    db_session.commit()

    body = client.get("/api/dashboard/capital-migration").json()

    assert body["sample_days"] == 5
    assert body["is_partial_window"] is True
    assert body["weak_to_strong"][0]["sector_code"] == "BK_SHORT"
    assert body["weak_to_strong"][0]["sample_days"] == 5
    assert body["weak_to_strong"][0]["is_partial_window"] is True


def test_capital_migration_detects_weak_to_strong(db_session, client):
    _seed_series(
        db_session,
        code="BK_W2S",
        name="弱转强",
        values=[-5] * 10 + [6] * 10,
    )
    db_session.commit()

    body = client.get("/api/dashboard/capital-migration").json()
    item = body["weak_to_strong"][0]

    assert item["sector_code"] == "BK_W2S"
    assert item["migration_status"] == "weak_to_strong"
    assert Decimal(item["first_half_sum_yi"]) == Decimal("-50")
    assert Decimal(item["second_half_sum_yi"]) == Decimal("60")
    assert Decimal(item["delta_yi"]) == Decimal("110")


def test_capital_migration_detects_strong_to_weak(db_session, client):
    _seed_series(
        db_session,
        code="BK_S2W",
        name="强转弱",
        values=[4] * 10 + [-7] * 10,
    )
    db_session.commit()

    body = client.get("/api/dashboard/capital-migration").json()
    item = body["strong_to_weak"][0]

    assert item["sector_code"] == "BK_S2W"
    assert item["migration_status"] == "strong_to_weak"
    assert Decimal(item["first_half_sum_yi"]) == Decimal("40")
    assert Decimal(item["second_half_sum_yi"]) == Decimal("-70")
    assert Decimal(item["delta_yi"]) == Decimal("-110")


def test_holdings_capital_migration_verified_mapping_participates(
    db_session,
    client,
):
    _seed_series(
        db_session,
        code="BK0490",
        name="半导体",
        values=[-3] * 10 + [5] * 10,
    )
    db_session.add(_fund("008281", "半导体基金", ["半导体"]))
    db_session.add(SectorAlias(
        chinese_label="半导体",
        sector_code="BK0490",
        sector_name="半导体",
        confidence=0.95,
    ))
    db_session.add(_holding("008281"))
    db_session.commit()

    body = client.get("/api/dashboard/holdings/capital-migration").json()
    item = body["holdings"][0]

    assert item["fund_code"] == "008281"
    assert item["mapping_status"] == "verified"
    assert item["sector_code"] == "BK0490"
    assert item["migration_status"] == "strengthening"
    assert Decimal(item["delta_yi"]) == Decimal("80")


def test_holdings_capital_migration_low_confidence_does_not_participate(
    db_session,
    client,
):
    _seed_series(
        db_session,
        code="BK_AI",
        name="人工智能",
        values=[-3] * 10 + [5] * 10,
    )
    db_session.add(_fund("123456", "人工智能基金", ["人工智能"]))
    db_session.add(SectorAlias(
        chinese_label="人工智能",
        sector_code="BK_AI",
        sector_name="人工智能",
        confidence=0.6,
    ))
    db_session.add(_holding("123456"))
    db_session.commit()

    body = client.get("/api/dashboard/holdings/capital-migration").json()
    item = body["holdings"][0]

    assert item["mapping_status"] == "low_confidence"
    assert item["migration_status"] == "insufficient_data"
    assert item["delta_yi"] is None
    assert item["inflow_days_20"] is None
