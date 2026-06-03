"""sector_mapping service 测试。"""

from src.models import Fund, SectorAlias
from src.services.sector_mapping import (
    coverage_report,
    get_sectors_for_fund,
    get_unmapped_labels,
    mapping_status_for_fund,
    resolve_fund_sector_mappings,
)


def _add_fund(db_session, code: str, name: str, sectors: list[str] | None = None):
    db_session.add(
        Fund(
            fund_code=code,
            fund_name=name,
            fund_type="混合型",
            related_sectors=sectors,
        )
    )
    db_session.commit()


def _add_alias(
    db_session,
    label: str,
    code: str | None,
    name: str | None = None,
    conf: float = 1.0,
):
    db_session.add(
        SectorAlias(
            chinese_label=label,
            sector_code=code,
            sector_name=name,
            confidence=conf,
        )
    )
    db_session.commit()


# ============ get_sectors_for_fund ============


def test_get_sectors_returns_mapped_codes(db_session):
    _add_fund(db_session, "022365", "永赢科技智选", ["CPO", "光模块"])
    _add_alias(db_session, "CPO", "BK1144", "光模块")
    _add_alias(db_session, "光模块", "BK1144", "光模块")
    codes = get_sectors_for_fund(db_session, "022365")
    # 两个标签都映射到同一 BK,应去重
    assert codes == ["BK1144"]


def test_get_sectors_returns_multiple_unique(db_session):
    _add_fund(db_session, "022365", "永赢", ["CPO", "半导体"])
    _add_alias(db_session, "CPO", "BK1144", "光模块")
    _add_alias(db_session, "半导体", "BK0490", "半导体")
    codes = get_sectors_for_fund(db_session, "022365")
    assert set(codes) == {"BK1144", "BK0490"}


def test_get_sectors_skips_null_codes(db_session):
    """label 在 alias 表里但 sector_code=NULL(显式无对应)— 应跳过。"""
    _add_fund(db_session, "161125", "易方达标普500", ["标普500", "美股"])
    _add_alias(db_session, "标普500", None, conf=0.0)
    _add_alias(db_session, "美股", None, conf=0.0)
    assert get_sectors_for_fund(db_session, "161125") == []


def test_get_sectors_mixed_some_null_some_mapped(db_session):
    _add_fund(db_session, "000979", "景顺", ["5G通信", "港股"])
    _add_alias(db_session, "5G通信", "BK0727", "5G概念")
    _add_alias(db_session, "港股", None, conf=0.0)
    assert get_sectors_for_fund(db_session, "000979") == ["BK0727"]


def test_get_sectors_unknown_fund_returns_empty(db_session):
    assert get_sectors_for_fund(db_session, "999999") == []


def test_get_sectors_no_related_sectors(db_session):
    _add_fund(db_session, "008281", "国泰CES", None)
    assert get_sectors_for_fund(db_session, "008281") == []


def test_get_sectors_empty_related_sectors(db_session):
    _add_fund(db_session, "008281", "国泰CES", [])
    assert get_sectors_for_fund(db_session, "008281") == []


def test_get_sectors_label_not_in_aliases(db_session):
    _add_fund(db_session, "008281", "国泰CES", ["未知标签"])
    assert get_sectors_for_fund(db_session, "008281") == []


# ============ resolve_fund_sector_mappings ============


def test_resolve_mapping_statuses_and_sorting_eligibility(db_session):
    _add_fund(
        db_session,
        "F_THEME",
        "主题测试基金",
        ["光伏", "人工智能", "半导体", "通信设备", "CPO"],
    )
    _add_alias(db_session, "光伏", "BK0429", "光伏设备", conf=0.6)
    _add_alias(db_session, "人工智能", "BK0800", "人工智能", conf=0.6)
    _add_alias(db_session, "半导体", "BK0490", "半导体", conf=1.0)
    _add_alias(db_session, "通信设备", "BK0736", "通信设备", conf=0.5)
    _add_alias(db_session, "CPO", "BK1144", "光模块", conf=1.0)

    mappings = resolve_fund_sector_mappings(db_session, "F_THEME")
    by_label = {m.label: m for m in mappings}

    assert by_label["光伏"].status == "low_confidence"
    assert by_label["人工智能"].status == "low_confidence"
    assert by_label["半导体"].status == "verified"
    assert by_label["通信设备"].status == "low_confidence"
    assert by_label["CPO"].status == "verified"
    assert by_label["半导体"].eligible_for_sorting is True
    assert by_label["CPO"].eligible_for_sorting is True
    assert by_label["光伏"].eligible_for_sorting is False
    assert mapping_status_for_fund(mappings) == "verified"


def test_resolve_mapping_distinguishes_unmapped_low_confidence_not_applicable(
    db_session,
):
    _add_fund(db_session, "F_MIXED", "混合测试基金", ["低置信", "海外", "未知"])
    _add_alias(db_session, "低置信", "BK_LOW", "低置信", conf=0.5)
    _add_alias(db_session, "海外", None, conf=0.0)

    mappings = resolve_fund_sector_mappings(db_session, "F_MIXED")
    by_label = {m.label: m for m in mappings}

    assert by_label["低置信"].status == "low_confidence"
    assert by_label["海外"].status == "not_applicable"
    assert by_label["未知"].status == "unmapped"
    assert mapping_status_for_fund(mappings) == "low_confidence"


# ============ get_unmapped_labels ============


def test_unmapped_labels_finds_missing(db_session):
    _add_fund(db_session, "008281", "A", ["半导体", "新标签1"])
    _add_fund(db_session, "022365", "B", ["CPO", "新标签2"])
    _add_alias(db_session, "半导体", "BK0490")
    _add_alias(db_session, "CPO", "BK1144")
    # 新标签 1 和 2 在 funds 里出现但 sector_aliases 没记录
    missing = get_unmapped_labels(db_session)
    assert missing == ["新标签1", "新标签2"]


def test_unmapped_labels_null_code_not_unmapped(db_session):
    """sector_code=NULL 是已显式记录的,不算 unmapped。"""
    _add_fund(db_session, "161125", "标普", ["标普500"])
    _add_alias(db_session, "标普500", None, conf=0.0)
    assert get_unmapped_labels(db_session) == []


# ============ coverage_report ============


def test_coverage_report_all_mapped(db_session):
    _add_fund(db_session, "022365", "永赢", ["CPO"])
    _add_fund(db_session, "008281", "国泰", ["半导体"])
    _add_alias(db_session, "CPO", "BK1144")
    _add_alias(db_session, "半导体", "BK0490")
    r = coverage_report(db_session)
    assert r["total"] == 2
    assert r["mapped"] == 2
    assert r["coverage_pct"] == 100.0
    assert r["unmapped_funds"] == []


def test_coverage_report_partial(db_session):
    _add_fund(db_session, "022365", "永赢", ["CPO"])
    _add_fund(db_session, "161125", "标普", ["标普500"])
    _add_fund(db_session, "999999", "未知", ["陌生标签"])
    _add_alias(db_session, "CPO", "BK1144")
    _add_alias(db_session, "标普500", None, conf=0.0)
    r = coverage_report(db_session)
    assert r["total"] == 3
    assert r["mapped"] == 1
    assert r["unmapped_count"] == 2
    assert r["coverage_pct"] == 33.3
    assert {f[0] for f in r["unmapped_funds"]} == {"161125", "999999"}
    # 陌生标签应在 unmapped_labels(标普500 不是,因为已 alias)
    assert "陌生标签" in r["unmapped_labels"]
    assert "标普500" not in r["unmapped_labels"]
