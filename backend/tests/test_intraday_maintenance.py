"""维护脚本测试(PR18)— clear_intraday_snapshot + check_intraday_status。

测试只调 run() / collect_status(),不走 main() CLI 入口(避免依赖真实 DB)。
唯一例外:argparse 必填参数缺失时的失败路径,因为 argparse 在 SessionLocal
被调用前就 exit 2。
"""

from datetime import date, datetime

import pytest

from scripts import check_intraday_status as check_mod
from scripts import clear_intraday_snapshot as clear_mod
from src.models import IntradaySectorFlow, SectorFlowDaily


def _mk_intraday(snapshot: datetime, code: str = "BK_X",
                 sector_type: str = "industry",
                 main_inflow_wan_x10000: int = 100_000_000,
                 change_pct_x10000: int | None = 210) -> IntradaySectorFlow:
    return IntradaySectorFlow(
        sector_code=code,
        sector_name="测试板块",
        sector_type=sector_type,
        trade_date=snapshot.date(),
        snapshot_time=snapshot,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        change_pct_x10000=change_pct_x10000,
    )


# =====================================================================
# clear_intraday_snapshot
# =====================================================================


def test_clear_deletes_matching_snapshot(db_session):
    s1 = datetime(2026, 6, 1, 14, 30)
    s2 = datetime(2026, 6, 1, 14, 40)
    db_session.add_all([
        _mk_intraday(s1, code="BK_A"),
        _mk_intraday(s1, code="BK_B"),
        _mk_intraday(s2, code="BK_C"),  # 不应被删
    ])
    db_session.commit()

    result = clear_mod.run(db_session, s1)

    assert result["deleted_count"] == 2
    assert result["snapshot_time"] == s1.isoformat()
    # 只剩 s2 那一条
    remaining = db_session.query(IntradaySectorFlow).all()
    assert len(remaining) == 1
    assert remaining[0].sector_code == "BK_C"


def test_clear_returns_zero_when_no_match(db_session):
    """空 DB 或没匹配 → 0,不报错。"""
    result = clear_mod.run(db_session, datetime(2026, 6, 1, 14, 30))
    assert result["deleted_count"] == 0


def test_clear_truncates_seconds_to_match_stored_minute_precision(db_session):
    """用户传 14:30:47 应能删 14:30 那批(intraday_fetcher 入库时已截到分钟)。"""
    canonical = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk_intraday(canonical))
    db_session.commit()

    sloppy = datetime(2026, 6, 1, 14, 30, 47, 123456)
    result = clear_mod.run(db_session, sloppy)

    assert result["deleted_count"] == 1
    assert db_session.query(IntradaySectorFlow).count() == 0


def test_clear_does_not_affect_sector_flow_daily(db_session):
    """红线:只删 intraday_sector_flow,不动 sector_flow_daily。"""
    db_session.add(SectorFlowDaily(
        sector_code="BK_DAILY",
        sector_name="收盘板块",
        sector_type="industry",
        trade_date=date(2026, 6, 1),
        main_inflow_wan_x10000=999_999_999,
    ))
    s = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk_intraday(s, code="BK_INTRA"))
    db_session.commit()

    clear_mod.run(db_session, s)

    # intraday 清掉,但 daily 一行还在
    assert db_session.query(IntradaySectorFlow).count() == 0
    assert db_session.query(SectorFlowDaily).count() == 1


def test_clear_cli_requires_snapshot_time_argument():
    """argparse:不传 --snapshot-time 应 exit 2(argparse 错)。"""
    with pytest.raises(SystemExit) as exc_info:
        clear_mod.main([])
    # argparse 的标准退出码
    assert exc_info.value.code == 2


def test_clear_cli_rejects_invalid_datetime_format():
    """非法 datetime 格式 → argparse 报错。"""
    with pytest.raises(SystemExit) as exc_info:
        clear_mod.main(["--snapshot-time", "not-a-date"])
    assert exc_info.value.code == 2


# =====================================================================
# check_intraday_status
# =====================================================================


def test_check_empty_db_no_crash(db_session):
    """空表 → total_rows=0,所有可选字段是 None / 空。不抛异常。"""
    status = check_mod.collect_status(db_session)
    assert status["total_rows"] == 0
    assert status["latest_snapshot_time"] is None
    assert status["latest_trade_date"] is None
    assert status["by_type"] == {}
    assert status["industry_top"] == []
    assert status["concept_top"] == []


def test_check_empty_print_report_does_not_raise(db_session, capsys):
    """空表 → print_report 输出 '暂无盘中数据' 并 return,不抛。"""
    status = check_mod.collect_status(db_session)
    check_mod.print_report(status)
    out = capsys.readouterr().out
    assert "暂无盘中数据" in out


def test_check_returns_latest_snapshot_only(db_session):
    """多 snapshot → latest_snapshot_time 是最大的;by_type 只统计 latest。"""
    s_old = datetime(2026, 6, 1, 9, 35)
    s_new = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday(s_old, code="BK_OLD", sector_type="industry"),
        _mk_intraday(s_new, code="BK_NEW1", sector_type="industry"),
        _mk_intraday(s_new, code="BK_NEW2", sector_type="industry"),
        _mk_intraday(s_new, code="BK_NEW_C", sector_type="concept"),
    ])
    db_session.commit()

    status = check_mod.collect_status(db_session)

    assert status["total_rows"] == 4
    assert status["latest_snapshot_time"] == s_new
    assert status["latest_trade_date"] == date(2026, 6, 1)
    # 只统计 latest snapshot:2 个 industry + 1 concept
    assert status["by_type"]["industry"] == 2
    assert status["by_type"]["concept"] == 1
    # industry_top 只来自 latest
    assert all(r.snapshot_time == s_new for r in status["industry_top"])


def test_check_top10_industry_sorted_by_inflow_desc(db_session):
    s = datetime(2026, 6, 1, 14, 30)
    # 3 个 industry,inflow 各异
    db_session.add_all([
        _mk_intraday(s, code="BK_SMALL", main_inflow_wan_x10000=1_000_000_000),
        _mk_intraday(s, code="BK_BIG", main_inflow_wan_x10000=12_000_000_000),
        _mk_intraday(s, code="BK_MID", main_inflow_wan_x10000=5_000_000_000),
    ])
    db_session.commit()

    status = check_mod.collect_status(db_session)
    codes = [r.sector_code for r in status["industry_top"]]
    assert codes == ["BK_BIG", "BK_MID", "BK_SMALL"]


def test_check_concept_count_zero_reported_when_no_concept(db_session, capsys):
    """只有 industry,没有 concept → print_report 写 'concept_count=0',不报错。"""
    db_session.add(_mk_intraday(
        datetime(2026, 6, 1, 14, 30),
        sector_type="industry",
    ))
    db_session.commit()

    status = check_mod.collect_status(db_session)
    check_mod.print_report(status)

    out = capsys.readouterr().out
    assert "concept_count=0" in out


def test_check_does_not_count_sector_flow_daily(db_session):
    """红线:check 只看 intraday_sector_flow,不计入 sector_flow_daily。"""
    db_session.add(SectorFlowDaily(
        sector_code="BK_D", sector_name="d", sector_type="industry",
        trade_date=date(2026, 6, 1),
        main_inflow_wan_x10000=1_000_000_000,
    ))
    db_session.commit()

    status = check_mod.collect_status(db_session)
    assert status["total_rows"] == 0
    assert status["latest_snapshot_time"] is None


# =====================================================================
# 格式化辅助
# =====================================================================


@pytest.mark.parametrize("wan_x10000,expected", [
    (12_000_000_000, "+120.0亿"),
    (-1_800_000_000, "-18.0亿"),
    (0, "0.0亿"),    # 0 持平不带 +/-
])
def test_fmt_yi(wan_x10000, expected):
    assert check_mod._fmt_yi(wan_x10000) == expected


@pytest.mark.parametrize("pct_x10000,expected", [
    (210, "+2.10%"),
    (-150, "-1.50%"),
    (0, "0.00%"),    # 0 持平不带 +/-
    (None, "n/a"),
])
def test_fmt_pct(pct_x10000, expected):
    assert check_mod._fmt_pct(pct_x10000) == expected
