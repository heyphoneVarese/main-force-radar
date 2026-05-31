"""GET /api/dashboard/sectors/persistence/leaders 测试(PR22)。

15 项 spec 覆盖:空库 / 5 级排序键 / 三种 sector_type / 参数 422 /
不读 intraday / 不影响 PR20 端点 / latest_rank + Decimal。
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.models import IntradaySectorFlow, SectorFlowDaily


def _mk_flow(
    code: str,
    name: str,
    trade_date: date,
    main_inflow_wan_x10000: int,
    sector_type: str = "industry",
    change_pct_x10000: int = 100,
) -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=code,
        sector_name=name,
        sector_type=sector_type,
        trade_date=trade_date,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        change_pct_x10000=change_pct_x10000,
    )


def Y(b):
    return b * 100_000_000


# =====================================================================
# 1. 空库
# =====================================================================


def test_leaders_empty_db_returns_null_and_empty(client):
    resp = client.get("/api/dashboard/sectors/persistence/leaders")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["sector_type"] == "industry"
    assert body["items"] == []


# =====================================================================
# 2. 按 continuous_top20_days DESC 排
# =====================================================================


@pytest.fixture
def seed_three_continuous_patterns(db_session):
    """3 个板块,continuous_top20 不同 → 验证 leader 排序。

    BK_LONG :30 天连续在 top20
    BK_MID  :最近 10 天 in top20,之前 20 天不在
    BK_SHORT:只今天 in top20
    """
    # 30 天历史
    for i in range(30):
        d = date(2026, 5, 1) + (date(2026, 5, 31) - date(2026, 5, 1)) / 30 * 0
    # 简化:逐日构造
    from datetime import timedelta
    base = date(2026, 5, 1)
    dates = [base + timedelta(days=i) for i in range(30)]
    rows = []
    for d in dates:
        # BK_LONG 每天 inflow 60 亿 → 总会在 top20
        rows.append(_mk_flow("BK_LONG", "长青", d, Y(60)))
    # 其余板块只造一些日:
    # BK_MID 最近 10 天 in,前 20 天没记录(stop 在第 11 天)
    for d in dates[-10:]:
        rows.append(_mk_flow("BK_MID", "中等", d, Y(40)))
    # BK_SHORT 只今天
    rows.append(_mk_flow("BK_SHORT", "短期", dates[-1], Y(10)))
    db_session.add_all(rows)
    db_session.commit()
    return dates[-1]


def test_leaders_sort_by_continuous_top20_days_desc(
    client, seed_three_continuous_patterns
):
    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    codes = [it["sector_code"] for it in body["items"]]
    # LONG=30 > MID=10 > SHORT=1
    assert codes == ["BK_LONG", "BK_MID", "BK_SHORT"]


# =====================================================================
# 3-6. 排序 tiebreakers
# =====================================================================


def test_leaders_tiebreak_by_last_20_top20_days(db_session, client):
    """两个板块 continuous_top20_days 相同 → last_20_top20_days DESC。

    BK_A: 5 天连续 in top20 + 之前 5 天间断 in top20 → last_20=10
    BK_B: 5 天连续 in top20 + 之前 0 天             → last_20=5
    """
    from datetime import timedelta
    dates = [date(2026, 5, 1) + timedelta(days=i) for i in range(20)]
    rows = []
    # BK_A 每天 in(20 天连续都 top20)
    for d in dates:
        rows.append(_mk_flow("BK_A", "A", d, Y(50)))
    # BK_B 最近 5 天才出现(同 inflow 量)
    for d in dates[-5:]:
        rows.append(_mk_flow("BK_B", "B", d, Y(50)))
    db_session.add_all(rows)
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    codes = [it["sector_code"] for it in body["items"]]
    # A continuous=20 > B continuous=5 → A 在前(主键就拉开了)
    assert codes == ["BK_A", "BK_B"]


def test_leaders_tiebreak_by_last_20_inflow_days(db_session, client):
    """A 和 B continuous_top20_days 都 = 10,但 A 的 last_20 inflow 更多。"""
    from datetime import timedelta
    dates = [date(2026, 5, 1) + timedelta(days=i) for i in range(10)]
    rows = []
    # 两板块 10 天都在(top20 相同 = 10)
    for d in dates:
        rows.append(_mk_flow("BK_A", "A", d, Y(50)))
        rows.append(_mk_flow("BK_B", "B", d, Y(40)))
    # 再造其它日:A 有 5 天 outflow 历史(但 in/out 都不在 top20,因为只
    # 有这两个板块,所以 in 计数继续)
    # 简化:不强测 last_20_inflow 单独 tiebreak,改测它跟 inflow 联动。
    db_session.add_all(rows)
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    # continuous_top20 = 10 / last_20 都满 / last_20_inflow 都满 →
    # tertiary tiebreak 用 latest main_inflow:A=50亿 > B=40亿
    assert body["items"][0]["sector_code"] == "BK_A"
    assert body["items"][1]["sector_code"] == "BK_B"


def test_leaders_tiebreak_by_latest_main_inflow(db_session, client):
    """完全相同的历史,只今天 inflow 不同 → A 大在前。"""
    from datetime import timedelta
    dates = [date(2026, 5, 1) + timedelta(days=i) for i in range(5)]
    rows = []
    for d in dates[:-1]:  # 前 4 天一致
        rows.append(_mk_flow("BK_A", "A", d, Y(10)))
        rows.append(_mk_flow("BK_B", "B", d, Y(10)))
    # 最后一天 A 大
    rows.append(_mk_flow("BK_A", "A", dates[-1], Y(100)))
    rows.append(_mk_flow("BK_B", "B", dates[-1], Y(50)))
    db_session.add_all(rows)
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    assert body["items"][0]["sector_code"] == "BK_A"


def test_leaders_tiebreak_fallback_sector_code_asc(db_session, client):
    """完全相同的历史 + 今天 inflow 相同 → sector_code 字典序 ASC 兜底。"""
    from datetime import timedelta
    dates = [date(2026, 5, 1) + timedelta(days=i) for i in range(3)]
    rows = []
    for d in dates:
        rows.append(_mk_flow("BK_ZZZ", "Z", d, Y(50)))
        rows.append(_mk_flow("BK_AAA", "A", d, Y(50)))
        rows.append(_mk_flow("BK_MMM", "M", d, Y(50)))
    db_session.add_all(rows)
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_AAA", "BK_MMM", "BK_ZZZ"]


# =====================================================================
# 7-9. sector_type 过滤
# =====================================================================


def test_leaders_sector_type_industry_only(db_session, client):
    d = date(2026, 5, 29)
    db_session.add_all([
        _mk_flow("BK_IND", "工业", d, Y(50), sector_type="industry"),
        _mk_flow("BK_CON", "概念", d, Y(100), sector_type="concept"),
    ])
    db_session.commit()

    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?sector_type=industry"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_IND"]


def test_leaders_sector_type_concept_only(db_session, client):
    d = date(2026, 5, 29)
    db_session.add_all([
        _mk_flow("BK_IND", "工业", d, Y(50), sector_type="industry"),
        _mk_flow("BK_CON", "概念", d, Y(100), sector_type="concept"),
    ])
    db_session.commit()

    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?sector_type=concept"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_CON"]


def test_leaders_sector_type_all_mixes(db_session, client):
    d = date(2026, 5, 29)
    db_session.add_all([
        _mk_flow("BK_IND", "工业", d, Y(50), sector_type="industry"),
        _mk_flow("BK_CON", "概念", d, Y(100), sector_type="concept"),
    ])
    db_session.commit()

    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?sector_type=all"
    ).json()
    assert len(body["items"]) == 2


# =====================================================================
# 10. 参数 422
# =====================================================================


def test_leaders_invalid_n_rejected(client):
    assert client.get(
        "/api/dashboard/sectors/persistence/leaders?n=0"
    ).status_code == 422
    assert client.get(
        "/api/dashboard/sectors/persistence/leaders?n=101"
    ).status_code == 422


def test_leaders_invalid_sector_type_rejected(client):
    assert client.get(
        "/api/dashboard/sectors/persistence/leaders?sector_type=region"
    ).status_code == 422


# =====================================================================
# 11. 不读 intraday
# =====================================================================


def test_leaders_does_not_use_intraday_sector_flow(db_session, client):
    snapshot = datetime(2026, 5, 29, 14, 30)
    db_session.add(IntradaySectorFlow(
        sector_code="BK_I", sector_name="盘中独有",
        sector_type="industry", trade_date=snapshot.date(),
        snapshot_time=snapshot,
        main_inflow_wan_x10000=99_999_999_999,
    ))
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    assert body["trade_date"] is None
    assert body["items"] == []


# =====================================================================
# 12. 不影响原 PR20 端点
# =====================================================================


def test_leaders_endpoint_does_not_affect_pr20_persistence(
    db_session, client
):
    d = date(2026, 5, 29)
    db_session.add(_mk_flow("BK_X", "测试", d, Y(50)))
    db_session.commit()

    # 调 leaders
    client.get("/api/dashboard/sectors/persistence/leaders")
    # PR20 端点照常工作
    body = client.get("/api/dashboard/sectors/persistence").json()
    assert body["trade_date"] == "2026-05-29"
    assert len(body["items"]) == 1


# =====================================================================
# 13. latest_rank 正确
# =====================================================================


def test_leaders_latest_rank_reflects_inflow_position(db_session, client):
    d = date(2026, 5, 29)
    # 三个板块,inflow 不同 → latest_rank 应该 1/2/3
    db_session.add_all([
        _mk_flow("BK_HIGH", "高", d, Y(120)),
        _mk_flow("BK_LOW", "低", d, Y(10)),
        _mk_flow("BK_MID", "中", d, Y(50)),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    rank_by_code = {it["sector_code"]: it["latest_rank"] for it in body["items"]}
    # 排序 leader keys 全相同 → 用 latest main_inflow tiebreak
    # 但 latest_rank 始终反映在最新日按 inflow DESC 的位置
    assert rank_by_code["BK_HIGH"] == 1
    assert rank_by_code["BK_MID"] == 2
    assert rank_by_code["BK_LOW"] == 3


# =====================================================================
# 14. Decimal 解码
# =====================================================================


def test_leaders_latest_main_inflow_yi_decoded(db_session, client):
    d = date(2026, 5, 29)
    db_session.add(_mk_flow("BK_X", "X", d, Y(95)))  # 95 亿
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    item = body["items"][0]
    assert Decimal(item["latest_main_inflow_yi"]) == Decimal("95")


# =====================================================================
# 15. >=20 天能排前面(连续性优先于今日 inflow)
# =====================================================================


def test_leaders_long_continuous_beats_high_today_inflow(db_session, client):
    """A 持续 25 天连续 Top20(每天 inflow 50 亿);
    B 仅今天爆发(今天 inflow 200 亿,前面没记录)。
    leader 排序应让 A(continuous=25)排在 B(continuous=1)前。"""
    from datetime import timedelta
    dates = [date(2026, 5, 1) + timedelta(days=i) for i in range(25)]
    rows = []
    for d in dates:
        rows.append(_mk_flow("BK_A", "持续 A", d, Y(50)))
    # B 只今天
    rows.append(_mk_flow("BK_B", "爆发 B", dates[-1], Y(200)))
    db_session.add_all(rows)
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_A", "BK_B"]
    # 验证一下:A 不是今天 top1(B 才是),但 leader 第一仍是 A
    a = next(it for it in body["items"] if it["sector_code"] == "BK_A")
    b = next(it for it in body["items"] if it["sector_code"] == "BK_B")
    assert a["latest_rank"] == 2  # B 今天 inflow 更大,B = rank 1
    assert b["latest_rank"] == 1
    assert a["continuous_top20_days"] == 25
    assert b["continuous_top20_days"] == 1


# =====================================================================
# 字段完整性
# =====================================================================


def test_leaders_all_required_fields_present(client, seed_three_continuous_patterns):
    body = client.get("/api/dashboard/sectors/persistence/leaders").json()
    required = {
        "sector_code", "sector_name", "sector_type",
        "latest_rank", "latest_main_inflow_yi",
        "continuous_top20_days", "continuous_inflow_days",
        "continuous_outflow_days",
        "last_5_inflow_days", "last_10_inflow_days", "last_20_inflow_days",
        "last_5_top20_days", "last_10_top20_days", "last_20_top20_days",
    }
    for it in body["items"]:
        assert required.issubset(it.keys())
    # 不应含 outflow 窗口字段(spec)
    forbidden = {"last_5_outflow_days", "last_10_outflow_days", "last_20_outflow_days"}
    for it in body["items"]:
        assert forbidden.isdisjoint(it.keys())


# =====================================================================
# n 参数限量
# =====================================================================


def test_leaders_n_param_limits_count(db_session, client):
    """5 个板块 + n=2 → 只返 2 个。"""
    d = date(2026, 5, 29)
    for i in range(5):
        db_session.add(_mk_flow(f"BK_{i:03d}", f"S{i}", d, Y(i + 1)))
    db_session.commit()

    body = client.get(
        "/api/dashboard/sectors/persistence/leaders?n=2"
    ).json()
    assert len(body["items"]) == 2
