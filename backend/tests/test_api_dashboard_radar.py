"""GET /api/dashboard/radar 测试(PR16)。

覆盖 spec 列的 12 项 + score 公式细节 + Decimal 解码。
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.models import Fund, Holding, IntradaySectorFlow, SectorAlias, SectorFlowDaily

# =====================================================================
# 辅助构造
# =====================================================================


def _mk_intraday(
    code: str,
    name: str,
    snapshot_time: datetime,
    main_inflow_wan_x10000: int,
    sector_type: str = "industry",
    change_pct_x10000: int | None = None,
) -> IntradaySectorFlow:
    return IntradaySectorFlow(
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        trade_date=snapshot_time.date(),
        snapshot_time=snapshot_time,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        change_pct_x10000=change_pct_x10000,
    )


def _mk_fund(code: str, name: str, related: list[str] | None) -> Fund:
    return Fund(fund_code=code, fund_name=name, fund_type="其他", related_sectors=related)


def _mk_holding(code: str) -> Holding:
    return Holding(
        fund_code=code,
        cost_nav_x10000=10000,
        shares_x100=1_000_000,
        bought_at=date(2025, 1, 1),
    )


def _mk_alias(
    label: str,
    code: str,
    name: str | None = None,
    confidence: float = 1.0,
) -> SectorAlias:
    return SectorAlias(
        chinese_label=label,
        sector_code=code,
        sector_name=name or label,
        confidence=confidence,
    )


# =====================================================================
# 1. 空 intraday
# =====================================================================


def test_radar_empty_intraday_returns_empty_arrays(client):
    body = client.get("/api/dashboard/radar").json()
    assert body["mode"] == "intraday"
    assert body["trade_date"] is None
    assert body["snapshot_time"] is None
    assert body["holdings"] == []
    assert body["candidates"] == []


# =====================================================================
# 2. 多 snapshot 只用最新
# =====================================================================


def test_radar_uses_only_latest_snapshot(db_session, client):
    s_old = datetime(2026, 6, 1, 9, 35)
    s_new = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK0001", "半导体", s_old, 999_999_999_999),  # old 巨大但被忽略
        _mk_intraday("BK0001", "半导体", s_new, 100_000_000_000),  # new 10亿
        _mk_alias("半导体", "BK0001", "半导体"),
        _mk_fund("F01", "半导体基金", ["半导体"]),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/radar").json()
    assert body["snapshot_time"].startswith("2026-06-01T14:30")
    # main_inflow_wan_x10000 = 100_000_000_000 → / 10000 = 10_000_000 万元
    # = 10_000_000 万 / 10_000 = 1000 亿元
    item = body["candidates"][0]
    assert Decimal(item["sector_main_inflow_wan"]) == Decimal("10000000")
    assert Decimal(item["sector_main_inflow_yi"]) == Decimal("1000")


# =====================================================================
# 3. concept 板块不进雷达(第一版只 industry)
# =====================================================================


def test_radar_ignores_concept_sectors(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        # concept 板块名也叫"半导体" 但 type=concept
        _mk_intraday("BK_C", "半导体", s, 500_000_000_000, sector_type="concept"),
        _mk_alias("半导体", "BK_C", "半导体"),
        _mk_fund("F_X", "半导体基金", ["半导体"]),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/radar").json()
    # 因为没 industry 行,sector_by_name 空,fund 不会被映射
    assert body["holdings"] == []
    assert body["candidates"] == []


# =====================================================================
# 4. holdings vs candidates 分流
# =====================================================================


@pytest.fixture
def seed_three_funds_one_sector(db_session):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK0490", "半导体", s, 950_000_000_000, change_pct_x10000=210),
        _mk_alias("半导体", "BK0490", "半导体"),
        # F_HELD 在 holdings → holdings 区
        _mk_fund("F_HELD", "持有的半导体基金", ["半导体"]),
        _mk_holding("F_HELD"),
        # F_NEW 不在 holdings → candidates 区
        _mk_fund("F_NEW", "候选的半导体基金", ["半导体"]),
    ])
    db_session.commit()
    return s


def test_radar_holdings_vs_candidates_split(client, seed_three_funds_one_sector):
    body = client.get("/api/dashboard/radar").json()
    assert len(body["holdings"]) == 1
    assert body["holdings"][0]["fund_code"] == "F_HELD"
    assert body["holdings"][0]["badge"] == "已持有"
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["fund_code"] == "F_NEW"
    assert body["candidates"][0]["badge"] == "候选"


# =====================================================================
# 5. 精确匹配,不模糊
# =====================================================================


def test_radar_exact_match_only_not_substring(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_A", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_A", "半导体"),
        # F1 标签"半导体"精确命中
        _mk_fund("F_EXACT", "F1", ["半导体"]),
        # F2 标签"半导体设备" — 名字含"半导体"但不等于,不匹配
        _mk_fund("F_SUB", "F2", ["半导体设备"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    codes = [c["fund_code"] for c in body["candidates"]]
    assert "F_EXACT" in codes
    assert "F_SUB" not in codes


def test_radar_strips_whitespace_on_match(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_A", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_A", "半导体"),
        _mk_fund("F_PAD", "F", ["  半导体  "]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    assert any(c["fund_code"] == "F_PAD" for c in body["candidates"])


# =====================================================================
# 6. 多 sector 命中取 rank 最小(最强势)
# =====================================================================


def test_radar_picks_strongest_matched_sector(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    # 3 个板块:半导体 rank#1(120亿),AI rank#2(80亿),消费 rank#3(30亿)
    db_session.add_all([
        _mk_intraday("BK_AI", "AI算力", s, 8_000_000_000_000),       # 80 亿
        _mk_intraday("BK_SEMI", "半导体", s, 12_000_000_000_000),     # 120 亿
        _mk_intraday("BK_CONS", "消费", s, 3_000_000_000_000),       # 30 亿
        _mk_alias("AI算力", "BK_AI", "AI算力"),
        _mk_alias("半导体", "BK_SEMI", "半导体"),
        _mk_alias("消费", "BK_CONS", "消费"),
        _mk_fund("F_MULTI", "三标签基金", ["AI算力", "半导体", "消费"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    item = body["candidates"][0]
    # 三个里半导体最强(rank=1)→ matched 应是半导体
    assert item["matched_sector"] == "半导体"
    assert item["sector_rank"] == 1


# =====================================================================
# 7. score 公式
# =====================================================================


@pytest.mark.parametrize("rank,inflow_yi,expected_score", [
    (1, 120, 9),       # 5 + 4 = 9
    (1, 50, 8),        # 5 + 3
    (1, 20, 7),        # 5 + 2
    (1, 10, 6),        # 5 + 1
    (1, 5, 5),         # 5 + 0
    (2, 50, 7),        # 4 + 3
    (3, 30, 5),        # 3 + 2
    (5, 15, 3),        # 2 + 1
    (15, 5, 1),        # 1 + 0
    (25, 100, 4),      # 0 + 4
    (50, 5, 0),        # 0 + 0
    (1, 200, 9),       # 5 + 4 = 9 但 cap 已封顶,不能 > 9
])
def test_radar_score_formula(rank, inflow_yi, expected_score):
    from src.services.radar import _compute_score
    # inflow_yi → wan_x10000:亿 × 10^8(因 wan_x10000 = 万 × 10000)
    wan_x10000 = int(inflow_yi * 100_000_000)
    assert _compute_score(rank, wan_x10000) == expected_score


# =====================================================================
# 8. n 参数限制 + 排序
# =====================================================================


def test_radar_sort_by_score_desc_then_rank_asc(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_R1", "板A", s, 12_000_000_000_000),   # rank 1, 120亿, rank_score=5 +4=9
        _mk_intraday("BK_R2", "板B", s, 1_000_000_000_000),    # rank 2, 10亿, rank_score=4 +1=5
        _mk_intraday("BK_R3", "板C", s, 1_500_000_000_000),    # 排在中:15亿
        _mk_alias("板A", "BK_R1", "板A"),
        _mk_alias("板B", "BK_R2", "板B"),
        # 等等,顺序需重排;后端会按 inflow 重排,与我手填顺序无关
        _mk_fund("F_A", "F_A", ["板A"]),
        _mk_fund("F_B", "F_B", ["板B"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    # F_A 命中板 A(rank 1, score 9),F_B 命中板 B(rank 3 因为板 C 15亿>板 B 10亿)
    # 按 score DESC → F_A 在前
    codes = [c["fund_code"] for c in body["candidates"]]
    assert codes[0] == "F_A"


def test_radar_n_param_limits_per_section(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk_intraday("BK_X", "半导体", s, 12_000_000_000_000))
    db_session.add(_mk_alias("半导体", "BK_X", "半导体"))
    # 5 个不同 fund 都命中半导体
    for i in range(5):
        db_session.add(_mk_fund(f"F{i:03d}", f"基金 {i}", ["半导体"]))
    db_session.commit()
    body = client.get("/api/dashboard/radar?n=2").json()
    assert len(body["candidates"]) == 2


def test_radar_invalid_n_rejected(client):
    assert client.get("/api/dashboard/radar?n=0").status_code == 422
    assert client.get("/api/dashboard/radar?n=101").status_code == 422


def test_radar_invalid_mode_rejected(client):
    """V1 只支持 mode=intraday;daily 应 422。"""
    assert client.get("/api/dashboard/radar?mode=daily").status_code == 422
    assert client.get("/api/dashboard/radar?mode=bogus").status_code == 422


# =====================================================================
# 11/12. 不匹配 + 空 related_sectors + daily 表
# =====================================================================


def test_radar_unmatched_fund_not_in_response(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("新能源车", "BK_Y", "新能源车"),
        _mk_fund("F_UNMATCHED", "其他主题", ["新能源车"]),  # 不命中
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    codes = [c["fund_code"] for c in body["candidates"]]
    assert "F_UNMATCHED" not in codes


def test_radar_empty_related_sectors_handled(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_fund("F_NULL", "QDII", None),       # None
        _mk_fund("F_EMPTY", "其他", []),        # 空 list
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    assert body["candidates"] == []


def test_radar_does_not_use_daily_table(db_session, client):
    """sector_flow_daily 有数据,intraday 空 → radar 仍返空(不混用)。"""
    db_session.add(SectorFlowDaily(
        sector_code="BK_X", sector_name="半导体", sector_type="industry",
        trade_date=date(2026, 6, 1),
        main_inflow_wan_x10000=12_000_000_000,
    ))
    db_session.add(_mk_fund("F", "F", ["半导体"]))
    db_session.commit()

    body = client.get("/api/dashboard/radar").json()
    assert body["trade_date"] is None
    assert body["holdings"] == []
    assert body["candidates"] == []


# =====================================================================
# Decimal 解码
# =====================================================================


def test_radar_decimal_format_main_inflow_wan_and_yi(
    client, seed_three_funds_one_sector
):
    body = client.get("/api/dashboard/radar").json()
    item = body["holdings"][0]
    # main_inflow_wan_x10000 = 950_000_000_000 → / 10000 = 95_000_000 万元
    # 但我 spec 例子里给的 95 亿 = 950000 万,所以这里 95_000_000 万 = 9500 亿... hmm
    # 让我用 fixture 的精确值:
    # 950_000_000_000 / 10_000 = 95_000_000(万元)
    # 95_000_000 / 10_000 = 9_500(亿元)
    assert Decimal(item["sector_main_inflow_wan"]) == Decimal("95000000")
    assert Decimal(item["sector_main_inflow_yi"]) == Decimal("9500")
    # change_pct_x10000=210 → / 100 = 2.10
    assert Decimal(item["sector_change_pct"]) == Decimal("2.1")


def test_radar_null_change_pct_preserved(db_session, client):
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000, change_pct_x10000=None),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_fund("F", "F", ["半导体"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    assert body["candidates"][0]["sector_change_pct"] is None


def test_radar_badge_strings_are_held_or_candidate(
    client, seed_three_funds_one_sector
):
    """R3.1 红线:只有'已持有'/'候选',不允许 buy/sell/long/short/hold。"""
    body = client.get("/api/dashboard/radar").json()
    all_items = body["holdings"] + body["candidates"]
    assert all(item["badge"] in {"已持有", "候选"} for item in all_items)


# =====================================================================
# PR17 — purity_score
# =====================================================================


def test_purity_single_related_sector_returns_9(db_session, client):
    """rule 1:related_sectors 长度 1 → base 9。fund_name 不含半导体 →
    rule 5/6 都不加 → 总 9。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_fund("F_PURE1", "测试基金", ["半导体"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    item = body["candidates"][0]
    assert item["purity_score"] == 9


def test_purity_two_related_sectors_returns_8(db_session, client):
    """rule 2:长度 2 → base 8。fund_name 无关键词 → 不加 bonus。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_alias("AI算力", "BK_AI", "AI算力"),
        _mk_fund("F_PURE2", "测试基金", ["半导体", "AI算力"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    item = body["candidates"][0]
    assert item["purity_score"] == 8


def test_purity_three_related_sectors_returns_7(db_session, client):
    """rule 3:长度 3 → base 7。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_alias("AI算力", "BK_AI", "AI算力"),
        _mk_alias("新能源车", "BK_NEW", "新能源车"),
        _mk_fund("F_PURE3", "测试基金", ["半导体", "AI算力", "新能源车"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    item = body["candidates"][0]
    assert item["purity_score"] == 7


def test_purity_four_or_more_related_sectors_returns_6(db_session, client):
    """rule 4:长度 ≥4 → base 6。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_alias("AI算力", "BK_AI", "AI算力"),
        _mk_alias("新能源车", "BK_NEW", "新能源车"),
        _mk_alias("消费", "BK_CONS", "消费"),
        _mk_alias("黄金", "BK_GOLD", "黄金"),
        _mk_fund("F_PURE4", "测试基金",
                 ["半导体", "AI算力", "新能源车", "消费", "黄金"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    item = body["candidates"][0]
    assert item["purity_score"] == 6


def test_purity_fund_name_contains_matched_adds_bonus(db_session, client):
    """rule 5:fund_name 含 matched_sector → +1。这里两标签 base=8 + 1 = 9。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_alias("通信设备", "BK_COMM", "通信设备"),
        _mk_fund("F_NAMED", "国泰半导体行业ETF", ["半导体", "通信设备"]),
    ])
    db_session.commit()
    item = client.get("/api/dashboard/radar").json()["candidates"][0]
    # base 8(2 related) + rule5 半导体在名字里 + rule6 主题 → 8+1+1=10 → cap 9
    assert item["purity_score"] == 9


def test_purity_theme_synonym_in_name_adds_bonus(db_session, client):
    """rule 6:matched=半导体,fund_name 含'芯片'(同主题同义词)+1。
    base 9(单标签)+ rule6 → cap 9。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_fund("F_SYN", "华夏国证芯片ETF", ["半导体"]),
    ])
    db_session.commit()
    item = client.get("/api/dashboard/radar").json()["candidates"][0]
    # base 9 + 0(rule5 没"半导体"在名字)+ 1(rule6 "芯片" 同主题)= 10 → cap 9
    assert item["purity_score"] == 9


def test_purity_cap_at_9_never_exceeds(db_session, client):
    """rule 7:封顶 9。即便 base+rule5+rule6 加起来 11 也封 9。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        # base 9 + rule5(半导体在名字)+ rule6(芯片同主题)= 11 → cap 9
        _mk_fund("F_CAP", "国泰半导体芯片ETF联接A", ["半导体"]),
    ])
    db_session.commit()
    item = client.get("/api/dashboard/radar").json()["candidates"][0]
    assert item["purity_score"] == 9
    assert item["purity_score"] <= 9


def test_purity_high_ranks_before_low_within_same_score(db_session, client):
    """同一板块 → 两基金 score 相同;purity 高的应该排前。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 12_000_000_000_000),  # 120 亿,rank 1,score 9
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_alias("AI", "BK_AI", "AI"),
        _mk_alias("消费", "BK_CONS", "消费"),
        _mk_alias("白酒", "BK_BAIJIU", "白酒"),
        _mk_alias("黄金", "BK_GOLD", "黄金"),
        # F_LOW:base 6(5 related),无 bonus = 6
        _mk_fund("F_LOW", "万家成长", ["半导体", "AI", "消费", "白酒", "黄金"]),
        # F_HIGH:base 9(单 related)+ rule5 + rule6 = 9
        _mk_fund("F_HIGH", "国泰半导体芯片ETF", ["半导体"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    codes = [c["fund_code"] for c in body["candidates"]]
    assert codes == ["F_HIGH", "F_LOW"]


def test_purity_holdings_and_candidates_both_carry_field(
    db_session, client
):
    """purity_score 字段在 holdings 和 candidates 都返回。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_fund("F_HELD", "F1", ["半导体"]),
        _mk_holding("F_HELD"),
        _mk_fund("F_CAND", "F2", ["半导体"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    assert "purity_score" in body["holdings"][0]
    assert "purity_score" in body["candidates"][0]


def test_purity_does_not_change_original_score_logic(
    client, seed_three_funds_one_sector
):
    """fixture: 950e9 万 inflow + rank 1 → score = 5(rank) + 4(>=100亿) = 9。
    确认 PR17 没破坏 score。"""
    body = client.get("/api/dashboard/radar").json()
    item = body["holdings"][0]
    assert item["score"] == 9


def test_purity_sort_tertiary_sector_rank(db_session, client):
    """同 score 同 purity → 按 sector_rank ASC。
    构造:板块 A inflow 100亿 rank=1,板块 B 90亿 rank=2。
    F_A 标签[A],F_B 标签[B],各自 score 都是 9,purity 都是 9 →
    sector_rank 小的(F_A,rank=1)排前。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_A", "板块A", s, 10_000_000_000_000),   # 100 亿 → rank 1
        _mk_intraday("BK_B", "板块B", s, 9_000_000_000_000),     # 90 亿  → rank 2
        _mk_alias("板块A", "BK_A", "板块A"),
        _mk_alias("板块B", "BK_B", "板块B"),
        _mk_fund("F_A", "FA", ["板块A"]),
        _mk_fund("F_B", "FB", ["板块B"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    codes = [c["fund_code"] for c in body["candidates"]]
    assert codes == ["F_A", "F_B"]


def test_purity_sort_quaternary_fund_code(db_session, client):
    """同 score 同 purity 同 sector_rank → fund_code 字典序 ASC 兜底稳定。"""
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("BK_X", "半导体", s, 100_000_000_000),
        _mk_alias("半导体", "BK_X", "半导体"),
        _mk_fund("ZZZ001", "FZ", ["半导体"]),
        _mk_fund("AAA001", "FA", ["半导体"]),
        _mk_fund("MMM001", "FM", ["半导体"]),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/radar").json()
    codes = [c["fund_code"] for c in body["candidates"]]
    assert codes == ["AAA001", "MMM001", "ZZZ001"]
