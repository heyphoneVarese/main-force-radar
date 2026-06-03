"""GET /api/dashboard/holdings-facts 测试(PR26)。

R3 红线:**不再返回** bullish / bearish / warning / neutral / signal_type /
persistence_score / score / health / rating 等情绪/评分字段。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.models import Fund, Holding, IntradaySectorFlow, SectorAlias, SectorFlowDaily


def Y(yi: float) -> int:
    return int(yi * 100_000_000)


def _mk(code: str, name: str, d: date, inflow_yi: float,
        sector_type: str = "industry") -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        trade_date=d,
        main_inflow_wan_x10000=Y(inflow_yi),
        change_pct_x10000=100,
    )


def _mk_fund(code: str, name: str, related: list[str]) -> Fund:
    return Fund(fund_code=code, fund_name=name, fund_type="其他",
                related_sectors=related)


def _mk_holding(code: str) -> Holding:
    return Holding(
        fund_code=code,
        cost_nav_x10000=10000,
        shares_x100=1_000_000,
        bought_at=date(2025, 1, 1),
    )


def _seed_streak(db_session, code: str, name: str, *, days: int,
                 base_end: date = date(2026, 5, 31),
                 inflow_yi: float = 50.0,
                 sector_type: str = "industry") -> None:
    """目标 sector 连续 days 天 in top20(本测试库小,自然 top1)。"""
    db_session.add(SectorAlias(
        chinese_label=name,
        sector_code=code,
        sector_name=name,
        confidence=1.0,
    ))
    for i in range(days):
        d = base_end - timedelta(days=i)
        db_session.add(_mk(code, name, d, inflow_yi, sector_type=sector_type))


# =====================================================================
# 1. 不再返回 bullish
# =====================================================================


def test_facts_response_does_not_contain_bullish(db_session, client):
    _seed_streak(db_session, "BK_A", "半导体", days=10)
    db_session.add_all([
        _mk_fund("F01", "半导体A", ["半导体"]),
        _mk_holding("F01"),
    ])
    db_session.commit()
    body_text = client.get("/api/dashboard/holdings-facts").text
    assert "bullish" not in body_text
    # 也禁止任何 signal_type 字段
    body = json.loads(body_text)
    for h in body["holdings"]:
        assert "signal_type" not in h
        assert "persistence_score" not in h
        assert "reason" not in h


# =====================================================================
# 2. 不再返回 bearish
# =====================================================================


def test_facts_response_does_not_contain_bearish(db_session, client):
    _seed_streak(db_session, "BK_A", "白酒", days=3, inflow_yi=-2.0)
    db_session.add_all([
        _mk_fund("F02", "白酒A", ["白酒"]),
        _mk_holding("F02"),
    ])
    db_session.commit()
    body_text = client.get("/api/dashboard/holdings-facts").text
    assert "bearish" not in body_text
    assert "warning" not in body_text
    assert "neutral" not in body_text


# =====================================================================
# 3. buckets 统计正确
# =====================================================================


def test_facts_buckets_counts(db_session, client):
    """4 个 sector 各档 + 1 个未映射 → buckets 1/1/1/1 total=4。"""
    # >=20:BK_LONG 连续 20 天 in top20
    _seed_streak(db_session, "BK_LONG", "长持续", days=20)
    # 5~19:BK_MID 连续 10 天
    _seed_streak(db_session, "BK_MID", "中持续", days=10)
    # <5:BK_SHORT 连续 2 天
    _seed_streak(db_session, "BK_SHORT", "短持续", days=2)
    # 未映射:fund 的 related 在 daily 找不到
    db_session.add_all([
        _mk_fund("F01", "Long", ["长持续"]),
        _mk_fund("F02", "Mid", ["中持续"]),
        _mk_fund("F03", "Short", ["短持续"]),
        _mk_fund("F04", "Unmapped", ["不存在的板块"]),
        _mk_holding("F01"),
        _mk_holding("F02"),
        _mk_holding("F03"),
        _mk_holding("F04"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    b = body["buckets"]
    assert b["persistence_ge_20"] == 1
    assert b["persistence_5_to_19"] == 1
    assert b["persistence_lt_5"] == 1
    assert b["verified"] == 3
    assert b["low_confidence"] == 0
    assert b["unmapped"] == 1
    assert b["not_applicable"] == 0
    assert b["total"] == 4
    # buckets 总和 = holdings 长度
    assert b["total"] == len(body["holdings"])


# =====================================================================
# 4. 连续Top20 分类正确(边界 19 → 5_to_19;20 → ge_20;4 → lt_5)
# =====================================================================


def test_facts_bucket_boundaries(db_session, client):
    _seed_streak(db_session, "BK_20", "二十", days=20)   # → ge_20
    _seed_streak(db_session, "BK_19", "十九", days=19)   # → 5_to_19
    _seed_streak(db_session, "BK_5", "五",   days=5)     # → 5_to_19
    _seed_streak(db_session, "BK_4", "四",   days=4)     # → lt_5
    db_session.add_all([
        _mk_fund(f"F{i:02d}", f"F{i:02d}", [name])
        for i, name in enumerate(["二十", "十九", "五", "四"])
    ])
    db_session.add_all([_mk_holding(f"F{i:02d}") for i in range(4)])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    b = body["buckets"]
    assert b["persistence_ge_20"] == 1
    assert b["persistence_5_to_19"] == 2
    assert b["persistence_lt_5"] == 1


# =====================================================================
# 5. 未映射:没 related_sectors 或匹配不到
# =====================================================================


def test_facts_unmapped_no_related_sectors(db_session, client):
    _seed_streak(db_session, "BK_A", "半导体", days=10)
    db_session.add_all([
        _mk_fund("F01", "QDII基金", []),   # 没 related_sectors
        _mk_holding("F01"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    assert body["buckets"]["unmapped"] == 0
    assert body["buckets"]["not_applicable"] == 1
    assert body["holdings"][0]["mapped_sector"] is None
    assert body["holdings"][0]["sector_code"] is None
    assert body["holdings"][0]["mapping_status"] == "not_applicable"
    assert body["holdings"][0]["continuous_top20_days"] is None
    assert body["holdings"][0]["latest_main_inflow_yi"] is None
    assert body["holdings"][0]["purity_score"] is None


def test_facts_unmapped_when_related_label_not_in_daily(db_session, client):
    _seed_streak(db_session, "BK_X", "半导体", days=5)
    db_session.add_all([
        _mk_fund("F01", "标签不在 DB 里的基金", ["臆造的板块"]),
        _mk_holding("F01"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    assert body["buckets"]["unmapped"] == 1
    assert body["buckets"]["low_confidence"] == 0
    assert body["buckets"]["not_applicable"] == 0
    assert body["holdings"][0]["mapped_sector"] is None
    assert body["holdings"][0]["mapping_status"] == "unmapped"


def test_facts_low_confidence_mapping_does_not_drive_facts(db_session, client):
    _seed_streak(db_session, "BK_PV", "光伏", days=5)
    db_session.flush()
    alias = db_session.query(SectorAlias).filter_by(chinese_label="光伏").one()
    alias.confidence = 0.6
    db_session.add_all([
        _mk_fund("F01", "光伏基金", ["光伏"]),
        _mk_holding("F01"),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/holdings-facts").json()
    h = body["holdings"][0]
    assert body["buckets"]["unmapped"] == 0
    assert body["buckets"]["low_confidence"] == 1
    assert body["buckets"]["not_applicable"] == 0
    assert h["mapped_sector"] is None
    assert h["sector_code"] == "BK_PV"
    assert h["sector_name"] == "光伏"
    assert h["mapping_status"] == "low_confidence"
    assert h["mapping_confidence"] == 0.6
    assert h["latest_main_inflow_yi"] is None


# =====================================================================
# 6. 兼容已有持仓分析:返回 holdings 列表,字段就绪给 UI 用
# =====================================================================


def test_facts_compatible_shape_for_holdings_card(db_session, client):
    _seed_streak(db_session, "BK_A", "半导体", days=15)
    db_session.add_all([
        _mk_fund("F01", "半导体ETF联接A", ["半导体"]),
        _mk_holding("F01"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    assert body["trade_date"] == "2026-05-31"
    assert "buckets" in body
    assert len(body["holdings"]) == 1
    h = body["holdings"][0]
    # 必备字段都在
    required = {
        "fund_code", "fund_name", "related_sectors",
        "mapped_sector", "sector_code", "sector_name",
        "mapping_status", "mapping_confidence", "mapping_source",
        "purity_score",
        "continuous_top20_days", "last_20_top20_days", "last_20_inflow_days",
        "latest_main_inflow_yi", "change_pct",
        "intraday_main_inflow_yi", "intraday_change_pct",
    }
    assert required.issubset(h.keys())
    # purity_score 是数字(≥ 0,≤ 9)
    assert isinstance(h["purity_score"], int)
    assert 0 <= h["purity_score"] <= 9


# =====================================================================
# 7. 不影响其它 Dashboard endpoint
# =====================================================================


def test_facts_does_not_affect_other_endpoints(db_session, client):
    _seed_streak(db_session, "BK_A", "半导体", days=10)
    db_session.add_all([
        _mk_fund("F01", "半导体A", ["半导体"]),
        _mk_holding("F01"),
    ])
    db_session.commit()

    # 旧 /holdings-summary 仍能跑(R 线 — 不影响)
    legacy = client.get("/api/dashboard/holdings-summary")
    assert legacy.status_code == 200
    # 调一次 facts 之后,其它 endpoint 仍然正常
    client.get("/api/dashboard/holdings-facts")
    assert client.get("/api/dashboard/holdings-summary").status_code == 200
    assert client.get("/api/dashboard/sectors/persistence").status_code == 200
    assert client.get(
        "/api/dashboard/sectors/persistence/leaders"
    ).status_code == 200
    assert client.get("/api/dashboard/sector-trends").status_code == 200
    assert client.get("/api/dashboard/radar").status_code == 200
    assert client.get(
        "/api/dashboard/holding-sector-alerts"
    ).status_code == 200


# =====================================================================
# 额外:空持仓
# =====================================================================


def test_facts_empty_holdings_zero_buckets(client):
    body = client.get("/api/dashboard/holdings-facts").json()
    assert body["trade_date"] is None
    assert body["holdings"] == []
    assert body["buckets"]["total"] == 0
    for k in (
        "persistence_ge_20", "persistence_5_to_19",
        "persistence_lt_5", "verified", "low_confidence",
        "unmapped", "not_applicable",
    ):
        assert body["buckets"][k] == 0


# =====================================================================
# 额外:intraday 数据透传
# =====================================================================


def test_facts_intraday_values_propagate(db_session, client):
    _seed_streak(db_session, "BK_A", "半导体", days=10)
    snap = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        IntradaySectorFlow(
            sector_code="BK_A", sector_name="半导体",
            sector_type="industry", trade_date=snap.date(),
            snapshot_time=snap,
            main_inflow_wan_x10000=Y(-379.3),
            change_pct_x10000=-640,
        ),
        _mk_fund("F01", "半导体A", ["半导体"]),
        _mk_holding("F01"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    assert body["snapshot_time"] is not None
    h = body["holdings"][0]
    assert Decimal(h["intraday_main_inflow_yi"]) < 0
    assert Decimal(h["intraday_change_pct"]) == Decimal("-6.40")
    # daily 字段也在
    assert Decimal(h["latest_main_inflow_yi"]) == Decimal("50")


# =====================================================================
# 额外:多 related_sectors 选 continuous_top20 最大的
# =====================================================================


def test_facts_picks_most_persistent_matched_sector(db_session, client):
    _seed_streak(db_session, "BK_LONG", "长", days=30)
    _seed_streak(db_session, "BK_SHORT", "短", days=2)
    db_session.add_all([
        _mk_fund("F01", "双标签", ["短", "长"]),
        _mk_holding("F01"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    h = body["holdings"][0]
    # mapped 应选连续天数更大的"长"
    assert h["mapped_sector"] == "长"
    assert h["continuous_top20_days"] == 30


# =====================================================================
# 额外:fund_code 顺序保持
# =====================================================================


def test_facts_sort_order_fund_code_asc(db_session, client):
    _seed_streak(db_session, "BK_A", "半导体", days=5)
    db_session.add_all([
        _mk_fund("F03", "F03", ["半导体"]),
        _mk_fund("F01", "F01", ["半导体"]),
        _mk_fund("F02", "F02", ["半导体"]),
        _mk_holding("F03"),
        _mk_holding("F01"),
        _mk_holding("F02"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holdings-facts").json()
    codes = [h["fund_code"] for h in body["holdings"]]
    assert codes == ["F01", "F02", "F03"]


# =====================================================================
# 额外:整个响应文本中不出现任何情绪/评分词
# =====================================================================


def test_facts_response_no_sentiment_or_rating_words(db_session, client):
    _seed_streak(db_session, "BK_A", "半导体", days=10)
    db_session.add_all([
        _mk_fund("F01", "半导体A", ["半导体"]),
        _mk_holding("F01"),
    ])
    db_session.commit()
    body_text = client.get("/api/dashboard/holdings-facts").text
    # 情绪
    for w in ["bullish", "bearish", "warning", "neutral"]:
        assert w not in body_text, f"{w} in response"
    # 旧字段
    for w in ["signal_type", "persistence_score", "health", "rating"]:
        assert w not in body_text, f"{w} in response"
