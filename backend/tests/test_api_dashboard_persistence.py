"""GET /api/dashboard/sectors/persistence 测试(PR20)。

15 项 spec 覆盖:空库 / Top N / 三种连续天数 / 缺失中断 / last_20 三种 /
三种 sector_type / 参数 422 / 不读 intraday / 不影响 sectors/top。
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


# =====================================================================
# 1. 空库
# =====================================================================


def test_persistence_empty_db_returns_null_date_and_empty(client):
    resp = client.get("/api/dashboard/sectors/persistence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert body["sector_type"] == "industry"
    assert body["items"] == []


# =====================================================================
# 2. 最新日 Top N + 按 main_inflow 降序
# =====================================================================


@pytest.fixture
def seed_three_sectors_5_days(db_session):
    """5 个交易日,3 个 industry 板块,inflow 模式各异。

    日期(最新在末):d1 < d2 < d3 < d4 < d5
    BK_SEMI(半导体):  +120, +100, +80, +60, +40 (5 天连续 in,排名 1)
    BK_PV(光伏):     -20, -30, -40, -50, -60   (5 天连续 out)
    BK_OTHER(其他):  +10, +50, -10, +30, -20  (今日 out,昨日 in)
    """
    d1 = date(2026, 5, 25)
    d2 = date(2026, 5, 26)
    d3 = date(2026, 5, 27)
    d4 = date(2026, 5, 28)
    d5 = date(2026, 5, 29)  # 最新

    def Y(b):
        return b * 100_000_000

    rows = [
        # SEMI:连续流入 5 天
        _mk_flow("BK_SEMI", "半导体", d1, Y(40)),
        _mk_flow("BK_SEMI", "半导体", d2, Y(60)),
        _mk_flow("BK_SEMI", "半导体", d3, Y(80)),
        _mk_flow("BK_SEMI", "半导体", d4, Y(100)),
        _mk_flow("BK_SEMI", "半导体", d5, Y(120)),
        # PV:连续流出 5 天
        _mk_flow("BK_PV", "光伏", d1, Y(-60)),
        _mk_flow("BK_PV", "光伏", d2, Y(-50)),
        _mk_flow("BK_PV", "光伏", d3, Y(-40)),
        _mk_flow("BK_PV", "光伏", d4, Y(-30)),
        _mk_flow("BK_PV", "光伏", d5, Y(-20)),
        # OTHER:今日流出,昨日流入
        _mk_flow("BK_OTHER", "其他", d1, Y(-20)),
        _mk_flow("BK_OTHER", "其他", d2, Y(30)),
        _mk_flow("BK_OTHER", "其他", d3, Y(-10)),
        _mk_flow("BK_OTHER", "其他", d4, Y(50)),
        _mk_flow("BK_OTHER", "其他", d5, Y(10)),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return d5


def test_persistence_returns_top_n_at_latest_date_inflow_desc(
    client, seed_three_sectors_5_days
):
    body = client.get("/api/dashboard/sectors/persistence").json()
    assert body["trade_date"] == "2026-05-29"
    codes = [it["sector_code"] for it in body["items"]]
    # 最新日 inflow:SEMI=+120 > OTHER=+10 > PV=-20
    assert codes == ["BK_SEMI", "BK_OTHER", "BK_PV"]
    # rank 是 1-based
    assert [it["rank"] for it in body["items"]] == [1, 2, 3]


# =====================================================================
# 3. continuous_inflow_days
# =====================================================================


def test_persistence_continuous_inflow_days_5_consecutive(
    client, seed_three_sectors_5_days
):
    body = client.get("/api/dashboard/sectors/persistence").json()
    semi = next(it for it in body["items"] if it["sector_code"] == "BK_SEMI")
    assert semi["continuous_inflow_days"] == 5
    # PV 今日是流出,所以 continuous_inflow_days = 0
    pv = next(it for it in body["items"] if it["sector_code"] == "BK_PV")
    assert pv["continuous_inflow_days"] == 0
    # OTHER 今日 +10(in)、昨日 +50(in)、前日 -10(out)→ 2 天
    other = next(it for it in body["items"] if it["sector_code"] == "BK_OTHER")
    assert other["continuous_inflow_days"] == 2


# =====================================================================
# 4. continuous_outflow_days
# =====================================================================


def test_persistence_continuous_outflow_days_5_consecutive(
    client, seed_three_sectors_5_days
):
    body = client.get("/api/dashboard/sectors/persistence").json()
    pv = next(it for it in body["items"] if it["sector_code"] == "BK_PV")
    assert pv["continuous_outflow_days"] == 5
    # SEMI 今日 in → 0
    semi = next(it for it in body["items"] if it["sector_code"] == "BK_SEMI")
    assert semi["continuous_outflow_days"] == 0


# =====================================================================
# 5. continuous_top20_days
# =====================================================================


def test_persistence_continuous_top20_days_when_always_in_top(
    client, seed_three_sectors_5_days
):
    """fixture 只 3 个 industry → 永远全在 top 20 → continuous = 5。"""
    body = client.get("/api/dashboard/sectors/persistence").json()
    for it in body["items"]:
        assert it["continuous_top20_days"] == 5


def test_persistence_continuous_top20_stops_at_missing_day(db_session, client):
    """造一个板块某天没出 top20 → continuous 应该在那里停。"""
    d1 = date(2026, 5, 27)
    d2 = date(2026, 5, 28)
    d3 = date(2026, 5, 29)

    def Y(b):
        return b * 100_000_000

    # 25 个 industry,确保有 top20 的边界
    other_rows = []
    for i in range(25):
        for d in (d1, d2, d3):
            # BK_X 在 d1/d3 inflow 高,在 d2 一些其它板块超过 → BK_X 掉出 top20
            other_rows.append(_mk_flow(
                f"BK_OTH_{i:02d}", f"其它{i}", d,
                # 在 d2 时,其它板块都比 BK_X 高
                Y(50 + i if d == d2 else 1 + i),
            ))
    db_session.add_all(other_rows)
    # BK_X 在 d3 最高,d2 较低,d1 最高
    db_session.add_all([
        _mk_flow("BK_X", "目标板块", d1, Y(200)),
        _mk_flow("BK_X", "目标板块", d2, Y(2)),    # 掉到 top20 外
        _mk_flow("BK_X", "目标板块", d3, Y(300)),  # 最新日 top1
    ])
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence?n=1").json()
    item = body["items"][0]
    assert item["sector_code"] == "BK_X"
    # 最新日 d3:in top20 ✓ → 1
    # 上一日 d2:不在 top20 → 停
    assert item["continuous_top20_days"] == 1


# =====================================================================
# 6. 缺失日期停止
# =====================================================================


def test_persistence_continuous_stops_when_sector_missing_a_day(
    db_session, client
):
    """SEMI 在 d3 缺记录 → continuous_inflow_days 应该在 d3 处停。"""
    d1 = date(2026, 5, 25)
    d2 = date(2026, 5, 26)
    # d3 故意整张表都没记录 — 但其它板块至少存在 d3 才会让 all_dates 含 d3
    # 这里测的是 "sector 在某日缺记录 → stop",故造个其它板块占住 d3
    d3 = date(2026, 5, 27)
    d4 = date(2026, 5, 28)
    d5 = date(2026, 5, 29)

    def Y(b):
        return b * 100_000_000

    db_session.add_all([
        _mk_flow("BK_SEMI", "半导体", d5, Y(120)),
        _mk_flow("BK_SEMI", "半导体", d4, Y(100)),
        # d3 SEMI 缺
        _mk_flow("BK_SEMI", "半导体", d2, Y(60)),
        _mk_flow("BK_SEMI", "半导体", d1, Y(40)),
        # 其它板块在 d3 出现,确保 all_dates 包含 d3
        _mk_flow("BK_OTHER", "其它", d3, Y(10)),
        _mk_flow("BK_OTHER", "其它", d5, Y(5)),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence?n=10").json()
    semi = next(it for it in body["items"] if it["sector_code"] == "BK_SEMI")
    # d5:✓ d4:✓ d3:SEMI 缺 → 停 → 2
    assert semi["continuous_inflow_days"] == 2


# =====================================================================
# 7-9. last_20 统计
# =====================================================================


def test_persistence_last_20_counts(client, seed_three_sectors_5_days):
    """fixture 5 天,所以 last_20 = 全部 5 天。"""
    body = client.get("/api/dashboard/sectors/persistence").json()
    semi = next(it for it in body["items"] if it["sector_code"] == "BK_SEMI")
    # SEMI:5 天全 in,全 top20
    assert semi["last_20_top20_days"] == 5
    assert semi["last_20_inflow_days"] == 5
    assert semi["last_20_outflow_days"] == 0

    pv = next(it for it in body["items"] if it["sector_code"] == "BK_PV")
    assert pv["last_20_inflow_days"] == 0
    assert pv["last_20_outflow_days"] == 5
    assert pv["last_20_top20_days"] == 5

    other = next(it for it in body["items"] if it["sector_code"] == "BK_OTHER")
    # OTHER 5 天: -20, +30, -10, +50, +10 → 3 in / 2 out
    assert other["last_20_inflow_days"] == 3
    assert other["last_20_outflow_days"] == 2


def test_persistence_last_20_caps_at_20_when_history_longer(db_session, client):
    """造 25 天数据,last_20 应只数最近 20 天。"""
    base = date(2026, 5, 1)

    def Y(b):
        return b * 100_000_000

    # 25 天连续 in 1 亿
    for i in range(25):
        d = date(2026, 5, 1 + i)
        db_session.add(_mk_flow("BK_LONG", "长青", d, Y(1)))
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence").json()
    item = body["items"][0]
    assert item["last_20_inflow_days"] == 20  # 不是 25
    assert item["last_20_top20_days"] == 20


# =====================================================================
# 10-12. sector_type 过滤
# =====================================================================


def test_persistence_sector_type_industry_only(db_session, client):
    d = date(2026, 5, 29)

    def Y(b):
        return b * 100_000_000

    db_session.add_all([
        _mk_flow("BK_IND", "工业", d, Y(50), sector_type="industry"),
        _mk_flow("BK_CON", "概念", d, Y(100), sector_type="concept"),
    ])
    db_session.commit()

    body = client.get(
        "/api/dashboard/sectors/persistence?sector_type=industry"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_IND"]


def test_persistence_sector_type_concept_only(db_session, client):
    d = date(2026, 5, 29)

    def Y(b):
        return b * 100_000_000

    db_session.add_all([
        _mk_flow("BK_IND", "工业", d, Y(50), sector_type="industry"),
        _mk_flow("BK_CON", "概念", d, Y(100), sector_type="concept"),
    ])
    db_session.commit()

    body = client.get(
        "/api/dashboard/sectors/persistence?sector_type=concept"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_CON"]


def test_persistence_sector_type_all_mixes(db_session, client):
    """all → 跨 industry/concept 按 inflow 排,合并 top n。"""
    d = date(2026, 5, 29)

    def Y(b):
        return b * 100_000_000

    db_session.add_all([
        _mk_flow("BK_IND_1", "工业1", d, Y(50), sector_type="industry"),
        _mk_flow("BK_CON_1", "概念1", d, Y(100), sector_type="concept"),
        _mk_flow("BK_IND_2", "工业2", d, Y(30), sector_type="industry"),
    ])
    db_session.commit()

    body = client.get(
        "/api/dashboard/sectors/persistence?sector_type=all"
    ).json()
    codes = [it["sector_code"] for it in body["items"]]
    assert codes == ["BK_CON_1", "BK_IND_1", "BK_IND_2"]


# =====================================================================
# 13. 参数校验
# =====================================================================


def test_persistence_invalid_n_rejected(client):
    assert client.get(
        "/api/dashboard/sectors/persistence?n=0"
    ).status_code == 422
    assert client.get(
        "/api/dashboard/sectors/persistence?n=101"
    ).status_code == 422


def test_persistence_invalid_sector_type_rejected(client):
    assert client.get(
        "/api/dashboard/sectors/persistence?sector_type=region"
    ).status_code == 422
    assert client.get(
        "/api/dashboard/sectors/persistence?sector_type=bogus"
    ).status_code == 422


# =====================================================================
# 14. 不读 intraday
# =====================================================================


def test_persistence_does_not_use_intraday_sector_flow(db_session, client):
    """intraday 表有数据 + daily 表为空 → 仍返空(不能混)。"""
    snapshot = datetime(2026, 5, 29, 14, 30)
    db_session.add(IntradaySectorFlow(
        sector_code="BK_INTRA", sector_name="盘中独有",
        sector_type="industry", trade_date=snapshot.date(),
        snapshot_time=snapshot,
        main_inflow_wan_x10000=100_000_000_000,
    ))
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence").json()
    assert body["trade_date"] is None
    assert body["items"] == []


# =====================================================================
# 15. 不影响原 /sectors/top
# =====================================================================


def test_persistence_endpoint_does_not_affect_sectors_top(
    client, seed_three_sectors_5_days
):
    """两端点同源 sector_flow_daily 但各自独立 — 调 persistence 不影响
    sectors/top 行为。"""
    # 先调 persistence
    client.get("/api/dashboard/sectors/persistence")

    # sectors/top 应正常返当前数据
    body = client.get("/api/dashboard/sectors/top").json()
    assert body["trade_date"] == "2026-05-29"
    assert len(body["sectors"]) == 3


# =====================================================================
# Decimal + 字段完整性
# =====================================================================


def test_persistence_main_inflow_yi_decoded_correctly(
    client, seed_three_sectors_5_days
):
    body = client.get("/api/dashboard/sectors/persistence").json()
    semi = next(it for it in body["items"] if it["sector_code"] == "BK_SEMI")
    # +120 × 1e8 → main_inflow_wan_x10000 = 12e9 → /1e8 = 120 亿
    assert Decimal(semi["main_inflow_yi"]) == Decimal("120")


def test_persistence_all_six_fact_fields_present(
    client, seed_three_sectors_5_days
):
    body = client.get("/api/dashboard/sectors/persistence").json()
    required_fields = {
        "continuous_inflow_days",
        "continuous_outflow_days",
        "continuous_top20_days",
        "last_20_top20_days",
        "last_20_inflow_days",
        "last_20_outflow_days",
    }
    for it in body["items"]:
        assert required_fields.issubset(it.keys())


# =====================================================================
# PR21 — 5 / 10 / 20 日窗口扩展
# =====================================================================


@pytest.fixture
def seed_history_25_days(db_session):
    """造 25 个连续交易日(d-24..d0)的数据。BK_X 有不同模式:
    - 全 25 天都 in 1 亿 → 25 天连续 inflow
    构造另一只 BK_Y 让 top20 视图非平凡:
    - 25 个其它板块每天都更强 → BK_X / BK_Y 大部分天不在 top20。
    BK_X 历史前 20 天(d-24..d-5)inflow 高,
    后 5 天(d-4..d0)inflow 也高 →  → BK_X 全在 top20。

    简化:只造 BK_X(25 天 inflow,top20 全在)+ BK_Y(25 天 outflow)。
    其它板块不造,top20 < 20 个但 BK_X/Y 仍在。
    """
    def Y(b):
        return b * 100_000_000

    base = date(2026, 5, 1)
    for i in range(25):
        d = date(2026, 5, 1 + i)
        # BK_X: 25 天连续 inflow
        db_session.add(_mk_flow("BK_X", "X", d, Y(10)))
        # BK_Y: 25 天连续 outflow
        db_session.add(_mk_flow("BK_Y", "Y", d, Y(-5)))
    db_session.commit()
    return date(2026, 5, 25)  # 最新日


def test_persistence_last_5_inflow_days(client, seed_history_25_days):
    """BK_X 25 天连续 inflow → last_5 = 5。"""
    body = client.get("/api/dashboard/sectors/persistence").json()
    x = next(it for it in body["items"] if it["sector_code"] == "BK_X")
    assert x["last_5_inflow_days"] == 5
    assert x["last_5_outflow_days"] == 0


def test_persistence_last_10_inflow_days(client, seed_history_25_days):
    body = client.get("/api/dashboard/sectors/persistence").json()
    x = next(it for it in body["items"] if it["sector_code"] == "BK_X")
    assert x["last_10_inflow_days"] == 10
    assert x["last_10_outflow_days"] == 0


def test_persistence_last_20_inflow_days_compat(client, seed_history_25_days):
    """PR20 兼容性 — last_20_inflow_days 仍然只算 20(不是 25)。"""
    body = client.get("/api/dashboard/sectors/persistence").json()
    x = next(it for it in body["items"] if it["sector_code"] == "BK_X")
    assert x["last_20_inflow_days"] == 20


def test_persistence_last_5_outflow_days(client, seed_history_25_days):
    body = client.get("/api/dashboard/sectors/persistence").json()
    y = next(it for it in body["items"] if it["sector_code"] == "BK_Y")
    assert y["last_5_outflow_days"] == 5
    assert y["last_5_inflow_days"] == 0


def test_persistence_last_10_outflow_days(client, seed_history_25_days):
    body = client.get("/api/dashboard/sectors/persistence").json()
    y = next(it for it in body["items"] if it["sector_code"] == "BK_Y")
    assert y["last_10_outflow_days"] == 10


def test_persistence_last_20_outflow_days_compat(client, seed_history_25_days):
    body = client.get("/api/dashboard/sectors/persistence").json()
    y = next(it for it in body["items"] if it["sector_code"] == "BK_Y")
    assert y["last_20_outflow_days"] == 20


def test_persistence_last_5_top20_days(client, seed_history_25_days):
    """只有 2 个板块 → 全在 top20(top20 容量 20) → last_5 = 5。"""
    body = client.get("/api/dashboard/sectors/persistence").json()
    x = next(it for it in body["items"] if it["sector_code"] == "BK_X")
    assert x["last_5_top20_days"] == 5


def test_persistence_last_10_top20_days(client, seed_history_25_days):
    body = client.get("/api/dashboard/sectors/persistence").json()
    x = next(it for it in body["items"] if it["sector_code"] == "BK_X")
    assert x["last_10_top20_days"] == 10


def test_persistence_last_20_top20_days_compat(client, seed_history_25_days):
    body = client.get("/api/dashboard/sectors/persistence").json()
    x = next(it for it in body["items"] if it["sector_code"] == "BK_X")
    assert x["last_20_top20_days"] == 20


# =====================================================================
# 历史不足窗口大小
# =====================================================================


def test_persistence_short_history_3_days_5d_caps_to_3(db_session, client):
    """只有 3 个交易日历史 → last_5_inflow_days 最多 3。"""
    def Y(b):
        return b * 100_000_000

    db_session.add_all([
        _mk_flow("BK_SHORT", "短", date(2026, 5, 27), Y(10)),
        _mk_flow("BK_SHORT", "短", date(2026, 5, 28), Y(10)),
        _mk_flow("BK_SHORT", "短", date(2026, 5, 29), Y(10)),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence").json()
    item = body["items"][0]
    assert item["last_5_inflow_days"] == 3   # 不是 5
    assert item["last_10_inflow_days"] == 3  # 不是 10
    assert item["last_20_inflow_days"] == 3  # 不是 20
    assert item["last_5_top20_days"] == 3
    assert item["last_10_top20_days"] == 3


# =====================================================================
# sector 某日缺失不计入
# =====================================================================


def test_persistence_missing_day_not_counted_in_windows(db_session, client):
    """BK_GAP 在 d3 缺记录 → last_5_inflow_days 只数实际存在的日。"""
    def Y(b):
        return b * 100_000_000

    d1 = date(2026, 5, 25)
    d2 = date(2026, 5, 26)
    d3 = date(2026, 5, 27)  # GAP 缺
    d4 = date(2026, 5, 28)
    d5 = date(2026, 5, 29)

    db_session.add_all([
        _mk_flow("BK_GAP", "缺日", d1, Y(10)),
        _mk_flow("BK_GAP", "缺日", d2, Y(10)),
        # d3 BK_GAP 缺
        _mk_flow("BK_GAP", "缺日", d4, Y(10)),
        _mk_flow("BK_GAP", "缺日", d5, Y(10)),
        # 其它板块占住 d3 让 all_dates 含 d3
        _mk_flow("BK_FILL", "填充", d3, Y(5)),
        _mk_flow("BK_FILL", "填充", d5, Y(5)),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence").json()
    gap = next(it for it in body["items"] if it["sector_code"] == "BK_GAP")
    # last_5 看最近 5 个交易日(d1..d5)中 BK_GAP 实际有数据的 = 4 天,都 inflow
    assert gap["last_5_inflow_days"] == 4


# =====================================================================
# 三种 sector_type
# =====================================================================


@pytest.fixture
def seed_industry_concept_history(db_session):
    """跨 industry/concept 各造 10 天数据。"""
    def Y(b):
        return b * 100_000_000

    base = date(2026, 5, 20)
    for i in range(10):
        d = date(2026, 5, 20 + i)
        db_session.add_all([
            _mk_flow("BK_IND", "工业", d, Y(20), sector_type="industry"),
            _mk_flow("BK_CON", "概念", d, Y(30), sector_type="concept"),
        ])
    db_session.commit()
    return date(2026, 5, 29)


def test_persistence_5_10_windows_industry(
    client, seed_industry_concept_history
):
    body = client.get(
        "/api/dashboard/sectors/persistence?sector_type=industry"
    ).json()
    assert len(body["items"]) == 1
    ind = body["items"][0]
    assert ind["last_5_inflow_days"] == 5
    assert ind["last_10_inflow_days"] == 10


def test_persistence_5_10_windows_concept(
    client, seed_industry_concept_history
):
    body = client.get(
        "/api/dashboard/sectors/persistence?sector_type=concept"
    ).json()
    con = body["items"][0]
    assert con["last_5_inflow_days"] == 5
    assert con["last_10_inflow_days"] == 10


def test_persistence_5_10_windows_all(
    client, seed_industry_concept_history
):
    """all → 跨类型合并,每个 item 仍带各自完整窗口字段。"""
    body = client.get(
        "/api/dashboard/sectors/persistence?sector_type=all"
    ).json()
    assert len(body["items"]) == 2
    for it in body["items"]:
        assert it["last_5_inflow_days"] == 5
        assert it["last_10_inflow_days"] == 10
        assert it["last_20_inflow_days"] == 10  # 历史只 10 天


# =====================================================================
# 不读 intraday + 兼容性兜底
# =====================================================================


def test_persistence_pr21_does_not_use_intraday(db_session, client):
    """intraday 有数据,daily 空 → 仍返空。"""
    snapshot = datetime(2026, 5, 29, 14, 30)
    db_session.add(IntradaySectorFlow(
        sector_code="BK_ID", sector_name="盘中", sector_type="industry",
        trade_date=snapshot.date(), snapshot_time=snapshot,
        main_inflow_wan_x10000=99_999_999_999,
    ))
    db_session.commit()

    body = client.get("/api/dashboard/sectors/persistence").json()
    assert body["items"] == []


def test_persistence_pr20_fields_still_present_after_pr21(
    client, seed_history_25_days
):
    """所有 PR20 字段 + 6 个 PR21 新字段都必须在 response 里。"""
    body = client.get("/api/dashboard/sectors/persistence").json()
    item = body["items"][0]
    required = {
        # PR20
        "continuous_inflow_days", "continuous_outflow_days",
        "continuous_top20_days",
        "last_20_inflow_days", "last_20_outflow_days", "last_20_top20_days",
        # PR21
        "last_5_inflow_days", "last_5_outflow_days", "last_5_top20_days",
        "last_10_inflow_days", "last_10_outflow_days", "last_10_top20_days",
    }
    assert required.issubset(item.keys())
