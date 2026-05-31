"""GET /api/dashboard/holding-sector-alerts 测试(PR23)。

覆盖 spec 列 15 项:
 1. 空库返回 200 + items=[]
 2. 没有 holdings 返回 items=[]
 3. holding_count < 2 不生成提醒
 4. holding_count >=2 + long persistence + intraday outflow
    → intraday_outflow_on_long_persistence
 5. holding_count >=2 + long persistence + intraday inflow
    → intraday_inflow_on_long_persistence
 6. continuous_outflow_days >=3 → continuous_outflow_holding_sector
 7. holding_count >=5 + continuous_top20 >=5 → concentrated_holding_sector
 8. intraday 为空时仍可生成 concentrated_holding_sector
 9. daily persistence 为空时返回空
10. 排序正确
11. message 不含禁词
12. 后端返回全部 fund_names(前端再截前 3)
13. n=0 / n=101 → 422
14. 不影响 radar endpoint
15. 不影响 persistence endpoints
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from src.models import Fund, Holding, IntradaySectorFlow, SectorFlowDaily


# =====================================================================
# 辅助
# =====================================================================


def Y(yi: float) -> int:
    """亿元 → main_inflow_wan_x10000 整数(× 1e8)。"""
    return int(yi * 100_000_000)


def _mk_fund(code: str, name: str, related: list[str]) -> Fund:
    return Fund(
        fund_code=code,
        fund_name=name,
        fund_type="其他",
        related_sectors=related,
    )


def _mk_holding(code: str) -> Holding:
    return Holding(
        fund_code=code,
        cost_nav_x10000=10000,
        shares_x100=1_000_000,
        bought_at=date(2025, 1, 1),
    )


def _mk_daily(
    sector_name: str,
    sector_code: str,
    trade_date: date,
    main_inflow_yi: float,
    sector_type: str = "industry",
) -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=sector_code,
        sector_name=sector_name,
        sector_type=sector_type,
        trade_date=trade_date,
        main_inflow_wan_x10000=Y(main_inflow_yi),
        change_pct_x10000=None,
    )


def _mk_intraday(
    sector_name: str,
    sector_code: str,
    snapshot_time: datetime,
    main_inflow_yi: float,
    sector_type: str = "industry",
    change_pct_x10000: int | None = None,
) -> IntradaySectorFlow:
    return IntradaySectorFlow(
        sector_code=sector_code,
        sector_name=sector_name,
        sector_type=sector_type,
        trade_date=snapshot_time.date(),
        snapshot_time=snapshot_time,
        main_inflow_wan_x10000=Y(main_inflow_yi),
        change_pct_x10000=change_pct_x10000,
    )


# 构造 30 个交易日,某 sector 持续 Top20(用于 A/B 类触发)
def _seed_long_persistence(
    db_session,
    sector_name: str,
    sector_code: str,
    *,
    days: int = 30,
    inflow_each_day_yi: float = 8.0,
) -> None:
    """sector 在过去 days 个交易日里:
    - 自己每天 inflow=+inflow_each_day_yi 亿(>0 → 算 inflow 天)
    - 同日构造 20 个其它 industry sector,inflow 都比它小 → 它进 Top20
      并按 inflow DESC 排名第 1(最强)。

    噪声 sector_code 用 sector_code 派生(`{sector_code}_N{j}`,truncate
    到 20 字符内)以避免多次调用相互冲突 UniqueConstraint。
    """
    base = date(2026, 5, 31)
    for i in range(days):
        d = base - timedelta(days=i)
        # 目标 sector
        db_session.add(
            _mk_daily(sector_name, sector_code, d, inflow_each_day_yi)
        )
        # 其它 20 个 industry sector(inflow 都 < target → target 排第 1)
        # noise_code 用 sector_code 派生,确保不同 _seed_long_persistence
        # 调用之间的噪声 sector_code 不冲突
        prefix = sector_code[:10]
        for j in range(20):
            db_session.add(_mk_daily(
                f"{prefix}_N{j}",
                f"{prefix}_N{j}",
                d,
                inflow_each_day_yi - 1 - j * 0.1,
            ))


# =====================================================================
# 1. 空库
# =====================================================================


def test_alerts_empty_db_returns_empty(client):
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert body["trade_date"] is None
    assert body["snapshot_time"] is None
    assert body["items"] == []


# =====================================================================
# 2. 有 daily 但没 holdings
# =====================================================================


def test_alerts_no_holdings_returns_empty(db_session, client):
    _seed_long_persistence(db_session, "半导体", "BK0490", days=15)
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert body["trade_date"] == "2026-05-31"
    assert body["items"] == []


# =====================================================================
# 3. holding_count < 2 → 不生成提醒
# =====================================================================


def test_alerts_single_holding_not_triggered(db_session, client):
    _seed_long_persistence(db_session, "半导体", "BK0490", days=15)
    db_session.add_all([
        _mk_fund("F01", "半导体ETF联接A", ["半导体"]),
        _mk_holding("F01"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    # holding_count=1,门槛 >=2;无 alert
    assert body["items"] == []


# =====================================================================
# 4. A 类:intraday_outflow_on_long_persistence
# =====================================================================


def test_alerts_intraday_outflow_on_long_persistence(db_session, client):
    _seed_long_persistence(db_session, "半导体", "BK0490", days=30)
    snap = datetime(2026, 6, 1, 14, 30)
    # intraday: 半导体净流出 -379.3 亿;同 snapshot 加几个 industry 作为分母
    db_session.add_all([
        _mk_intraday("半导体", "BK0490", snap, -379.3, change_pct_x10000=-640),
        _mk_intraday("其它行业A", "BK9100", snap, 50.0),
        _mk_intraday("其它行业B", "BK9101", snap, 30.0),
        _mk_fund("F01", "半导体ETF联接A", ["半导体"]),
        _mk_fund("F02", "半导体产业混合", ["半导体"]),
        _mk_fund("F03", "芯片半导体C", ["半导体"]),
        _mk_holding("F01"),
        _mk_holding("F02"),
        _mk_holding("F03"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["sector_name"] == "半导体"
    assert it["alert_type"] == "intraday_outflow_on_long_persistence"
    assert it["holding_count"] == 3
    assert it["continuous_top20_days"] == 30
    assert Decimal(it["intraday_main_inflow_yi"]) < 0
    # rank: 该 snapshot industry 内按 inflow DESC,半导体 -379 排最后
    assert it["intraday_rank"] == 3
    assert body["snapshot_time"] is not None
    # message:不含禁词
    msg = it["message"]
    for banned in ["买入", "卖出", "加仓", "减仓", "推荐", "建议",
                    "看多", "看空", "危险", "机会", "应该"]:
        assert banned not in msg, f"禁词 {banned} 出现在 message"
    assert "3" in msg and "半导体" in msg
    assert "净流出" in msg


# =====================================================================
# 5. B 类:intraday_inflow_on_long_persistence
# =====================================================================


def test_alerts_intraday_inflow_on_long_persistence(db_session, client):
    _seed_long_persistence(db_session, "半导体", "BK0490", days=12)
    snap = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("半导体", "BK0490", snap, 88.5),
        _mk_intraday("其它", "BK9101", snap, 20.0),
        _mk_fund("F01", "半导体A", ["半导体"]),
        _mk_fund("F02", "半导体B", ["半导体"]),
        _mk_holding("F01"),
        _mk_holding("F02"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["alert_type"] == "intraday_inflow_on_long_persistence"
    assert "净流入" in it["message"]
    assert Decimal(it["intraday_main_inflow_yi"]) > 0


# =====================================================================
# 6. C 类:continuous_outflow_holding_sector
# =====================================================================


def test_alerts_continuous_outflow_holding_sector(db_session, client):
    # 构造 sector 连续 5 天净流出(>=3 触发 C),且 continuous_top20 < 10
    # (避免 A/B 优先级抢)
    base = date(2026, 5, 31)
    sector_name = "白酒"
    sector_code = "BK0721"
    # 连续 5 天净流出,该 sector 也不出现在前 20(让 continuous_top20=0)
    for i in range(5):
        d = base - timedelta(days=i)
        db_session.add(_mk_daily(sector_name, sector_code, d, -3.0))
        # 加 20 个比它强的 industry,让该 sector 不在 top20
        for j in range(20):
            db_session.add(_mk_daily(
                f"Strong{j}", f"BK9{j:03d}", d, 50.0 + j,
            ))
    db_session.add_all([
        _mk_fund("F01", "白酒A", ["白酒"]),
        _mk_fund("F02", "白酒B", ["白酒"]),
        _mk_holding("F01"),
        _mk_holding("F02"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["alert_type"] == "continuous_outflow_holding_sector"
    assert it["continuous_outflow_days"] >= 3
    assert "连续净流出" in it["message"]


# =====================================================================
# 7. D 类:concentrated_holding_sector
# =====================================================================


def test_alerts_concentrated_holding_sector(db_session, client):
    # continuous_top20 = 6(>=5),holding_count = 5(>=5),
    # 但 < 10 天 + 无 intraday → 不会被 A/B/C 抢
    _seed_long_persistence(db_session, "新能源", "BK0429", days=6)
    db_session.add_all([
        _mk_fund("F01", "新能源A", ["新能源"]),
        _mk_fund("F02", "新能源B", ["新能源"]),
        _mk_fund("F03", "新能源C", ["新能源"]),
        _mk_fund("F04", "新能源D", ["新能源"]),
        _mk_fund("F05", "新能源E", ["新能源"]),
        _mk_holding("F01"),
        _mk_holding("F02"),
        _mk_holding("F03"),
        _mk_holding("F04"),
        _mk_holding("F05"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["alert_type"] == "concentrated_holding_sector"
    assert it["holding_count"] == 5
    assert it["continuous_top20_days"] == 6
    assert "持仓较为集中" in it["message"]


# =====================================================================
# 8. intraday 空时仍生成 D
# =====================================================================


def test_alerts_concentrated_without_intraday(db_session, client):
    # 没插任何 intraday 数据;但有 daily + 持仓
    _seed_long_persistence(db_session, "AI", "BK0498", days=8)
    db_session.add_all([
        _mk_fund(f"F0{i}", f"AI基金{i}", ["AI"]) for i in range(1, 6)
    ])
    db_session.add_all([_mk_holding(f"F0{i}") for i in range(1, 6)])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert body["snapshot_time"] is None  # intraday 空
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert it["alert_type"] == "concentrated_holding_sector"
    assert it["intraday_main_inflow_yi"] is None
    assert it["intraday_rank"] is None


# =====================================================================
# 9. daily 为空 → items=[]
# =====================================================================


def test_alerts_no_daily_returns_empty(db_session, client):
    # 只有 holdings,没 daily / intraday
    db_session.add_all([
        _mk_fund("F01", "F01 name", ["X"]),
        _mk_fund("F02", "F02 name", ["X"]),
        _mk_holding("F01"),
        _mk_holding("F02"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert body["trade_date"] is None
    assert body["items"] == []


# =====================================================================
# 10. 排序:holding_count DESC, continuous_top20 DESC, |intraday| DESC
# =====================================================================


def test_alerts_sort_by_holding_count_then_top20(db_session, client):
    """SectorA: holding_count=5, continuous_top20>=5 → D 类
       SectorB: holding_count=2, continuous_top20>=10 + intraday → A/B 类
       排序键第一位是 holding_count DESC → A 优先。
    """
    base = date(2026, 5, 31)
    # 30 个交易日,SectorA / SectorB / 18 filler(共 20 industry/day)
    # SectorA 和 SectorB 都稳定在 Top20 内(都是+10)
    for i in range(30):
        d = base - timedelta(days=i)
        db_session.add(_mk_daily("SectorA", "BK0001", d, 10.0))
        db_session.add(_mk_daily("SectorB", "BK0002", d, 10.0))
        for j in range(18):
            db_session.add(_mk_daily(
                f"FillerS{j}", f"BKS{j:02d}", d, 1.0 + j * 0.5,
            ))

    snap = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk_intraday("SectorB", "BK0002", snap, 80.0))

    db_session.add_all([
        _mk_fund(f"FA{i}", f"FA{i} name", ["SectorA"]) for i in range(5)
    ])
    db_session.add_all([_mk_holding(f"FA{i}") for i in range(5)])
    db_session.add_all([
        _mk_fund("FB1", "FB1 name", ["SectorB"]),
        _mk_fund("FB2", "FB2 name", ["SectorB"]),
        _mk_holding("FB1"),
        _mk_holding("FB2"),
    ])
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    names = [it["sector_name"] for it in body["items"]]
    assert names == ["SectorA", "SectorB"]
    # 同时验证 holding_count 排序占主导
    counts = [it["holding_count"] for it in body["items"]]
    assert counts == [5, 2]


# =====================================================================
# 11. 全部 message 不含禁词
# =====================================================================


_BANNED_WORDS = [
    "买入", "卖出", "加仓", "减仓", "推荐", "建议",
    "看多", "看空", "危险", "机会", "应该",
]


def test_alerts_messages_have_no_banned_words(db_session, client):
    """同一 DB 内 4 种 alert 共存 → 校验全部 message 无禁词。

    构造受控环境:每个交易日只有
      SectorA(+10), SectorB(+10), SectorD(+10), SectorC(-2),
      filler1..filler17(inflow 1..17)
    共 21 个 industry row。Top20 取最高 20 → A/B/D + 全部 17 fillers
    入 top20;SectorC 永远落在 21 位。这样 A/B/D 的 continuous_top20=days,
    SectorC 的 continuous_outflow=days。
    """
    base = date(2026, 5, 31)
    days = 30
    for i in range(days):
        d = base - timedelta(days=i)
        # 3 个主线
        db_session.add(_mk_daily("SectorA", "BK0001", d, 10.0))
        db_session.add(_mk_daily("SectorB", "BK0002", d, 10.0))
        db_session.add(_mk_daily("SectorD", "BK0004", d, 10.0))
        # SectorC:持续净流出
        db_session.add(_mk_daily("SectorC", "BK0003", d, -2.0))
        # 17 个 filler(每日各自唯一 code),inflow 1..9.5 让 top20 满
        for j in range(17):
            db_session.add(_mk_daily(
                f"FillerM{j}", f"BKF{j:02d}", d, 1.0 + j * 0.5,
            ))

    snap = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("SectorA", "BK0001", snap, -50.0),  # A 类触发器
        _mk_intraday("SectorB", "BK0002", snap, 60.0),   # B 类触发器
        # 不给 SectorD / SectorC 加 intraday(避免 D/C 被 A/B 优先级覆盖)
    ])

    # 持仓
    for s, codes in [
        ("SectorA", ["A1", "A2"]),       # holding_count=2 → A
        ("SectorB", ["B1", "B2"]),       # holding_count=2 → B
        ("SectorC", ["C1", "C2"]),       # holding_count=2 → C
        ("SectorD", ["D1", "D2", "D3", "D4", "D5"]),  # holding_count=5 → D
    ]:
        for c in codes:
            db_session.add(_mk_fund(c, f"{c} name", [s]))
            db_session.add(_mk_holding(c))

    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    types = {it["alert_type"] for it in body["items"]}
    assert "intraday_outflow_on_long_persistence" in types
    assert "intraday_inflow_on_long_persistence" in types
    assert "continuous_outflow_holding_sector" in types
    assert "concentrated_holding_sector" in types
    for it in body["items"]:
        for w in _BANNED_WORDS:
            assert w not in it["message"], f"{w} in {it['message']}"


# =====================================================================
# 12. 后端返回全部 fund_names(前端再截)
# =====================================================================


def test_alerts_returns_all_fund_names_backend(db_session, client):
    _seed_long_persistence(db_session, "AI", "BK0498", days=8)
    # 5 只持仓
    codes = ["F1", "F2", "F3", "F4", "F5"]
    for c in codes:
        db_session.add(_mk_fund(c, f"AI基金{c}", ["AI"]))
        db_session.add(_mk_holding(c))
    db_session.commit()
    body = client.get("/api/dashboard/holding-sector-alerts").json()
    assert len(body["items"]) == 1
    it = body["items"][0]
    assert len(it["holding_fund_codes"]) == 5
    assert len(it["holding_fund_names"]) == 5
    assert sorted(it["holding_fund_codes"]) == sorted(codes)


# =====================================================================
# 13. n=0 / n=101 → 422
# =====================================================================


def test_alerts_invalid_n_rejected(client):
    assert client.get("/api/dashboard/holding-sector-alerts?n=0").status_code == 422
    assert client.get("/api/dashboard/holding-sector-alerts?n=101").status_code == 422
    assert client.get("/api/dashboard/holding-sector-alerts?n=-1").status_code == 422


# =====================================================================
# 14. 不影响 radar
# =====================================================================


def test_alerts_does_not_affect_radar(db_session, client):
    _seed_long_persistence(db_session, "X", "BK0X", days=10)
    snap = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday("X", "BK0X", snap, 30.0),
        _mk_fund("F1", "F1 name", ["X"]),
        _mk_holding("F1"),
    ])
    db_session.commit()
    # radar 仍然能跑且包含 F1
    radar = client.get("/api/dashboard/radar").json()
    assert radar["mode"] == "intraday"
    assert any(h["fund_code"] == "F1" for h in radar["holdings"])
    # alerts 端点不破坏 radar 端点(单调性)
    client.get("/api/dashboard/holding-sector-alerts")
    radar2 = client.get("/api/dashboard/radar").json()
    assert radar == radar2


# =====================================================================
# 15. 不影响 persistence + leaders
# =====================================================================


def test_alerts_does_not_affect_persistence_endpoints(db_session, client):
    _seed_long_persistence(db_session, "X", "BK0X", days=8)
    db_session.add_all([
        _mk_fund(f"F{i}", f"F{i} name", ["X"]) for i in range(5)
    ])
    db_session.add_all([_mk_holding(f"F{i}") for i in range(5)])
    db_session.commit()
    p1 = client.get("/api/dashboard/sectors/persistence").json()
    l1 = client.get("/api/dashboard/sectors/persistence/leaders").json()
    client.get("/api/dashboard/holding-sector-alerts")
    p2 = client.get("/api/dashboard/sectors/persistence").json()
    l2 = client.get("/api/dashboard/sectors/persistence/leaders").json()
    assert p1 == p2
    assert l1 == l2
