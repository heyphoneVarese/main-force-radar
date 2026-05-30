"""import_candidate_funds 脚本最小测试(Phase 5.1 PR14)。

跟 test_import_real_holdings 风格一致 — 模块导入 + 用内存 DB session
直接调 run(),断言 stats + DB 状态。
"""

from __future__ import annotations

from src.models import Fund
from scripts import import_candidate_funds as mod


# =====================================================================
# CANDIDATE_FUNDS 数据自身的健全性
# =====================================================================


def test_candidate_pool_codes_all_6_digits():
    """红线:所有 fund_code 必须 6 位数字,不能混进 TODO 占位。"""
    from src.utils.fund_code import is_valid_fund_code
    for entry in mod.CANDIDATE_FUNDS:
        code = entry["fund_code"]
        assert is_valid_fund_code(code), f"invalid code in pool: {code!r}"


def test_candidate_pool_names_non_empty():
    for entry in mod.CANDIDATE_FUNDS:
        assert entry.get("fund_name", "").strip(), \
            f"empty fund_name for {entry.get('fund_code')}"


def test_candidate_pool_no_internal_duplicate_codes():
    """池内不应有同一 fund_code 两次出现(否则编辑列表时容易遗漏)。"""
    codes = [e["fund_code"] for e in mod.CANDIDATE_FUNDS]
    seen: set[str] = set()
    dups: list[str] = []
    for c in codes:
        if c in seen:
            dups.append(c)
        seen.add(c)
    assert not dups, f"duplicate fund_code in CANDIDATE_FUNDS: {dups}"


def test_candidate_pool_covers_required_sector_directions():
    """spec 列出的 10 个方向必须每个至少有 1 个候选基金覆盖到。
    检测方式:related_sectors 出现关键词。"""
    all_labels: set[str] = set()
    for entry in mod.CANDIDATE_FUNDS:
        for s in entry.get("related_sectors") or []:
            all_labels.add(s)

    # 每个方向至少能匹配一个关键词
    required_groups = [
        ["半导体", "芯片", "集成电路"],
        ["人工智能", "算力", "CPO", "光模块"],
        ["机器人", "智能制造"],
        ["电力", "电网", "储能"],
        ["军工", "卫星", "商业航天", "国防"],
        ["黄金", "有色金属"],
        ["红利", "银行"],
        ["消费", "白酒"],
        ["新能源车", "电池", "光伏", "新能源"],
        ["科创板", "创业板", "数字经济"],
    ]
    for group in required_groups:
        hit = any(kw in all_labels for kw in group)
        assert hit, f"no candidate covers any of {group}; got labels={all_labels}"


# =====================================================================
# run() 行为
# =====================================================================


def test_run_inserts_new_funds(db_session):
    """空 DB → 全部 insert,skipped=0。"""
    stats = mod.run(db_session)
    assert stats["inserted_count"] == len(mod.CANDIDATE_FUNDS)
    assert stats["skipped_count"] == 0
    assert stats["invalid_count"] == 0
    assert stats["total_funds_count"] == len(mod.CANDIDATE_FUNDS)


def test_run_skips_existing_funds_does_not_overwrite(db_session):
    """已存在的 fund_code 跳过,不覆盖现有 fund_name / fund_type。"""
    # 预置:候选池里第一只用一个 *不同的* 名字提前插
    pre = mod.CANDIDATE_FUNDS[0]
    db_session.add(Fund(
        fund_code=pre["fund_code"],
        fund_name="预置的不同名字",
        fund_type="预置类型",
        related_sectors=["预置标签"],
    ))
    db_session.commit()

    stats = mod.run(db_session)

    assert stats["skipped_count"] >= 1
    assert pre["fund_code"] in stats["skipped"]
    # 已存在的那只:fund_name 没被覆盖
    existing = db_session.get(Fund, pre["fund_code"])
    assert existing.fund_name == "预置的不同名字"
    assert existing.fund_type == "预置类型"
    assert existing.related_sectors == ["预置标签"]


def test_run_preserves_related_sectors_chinese_labels(db_session):
    """新 insert 的基金应保留中文 related_sectors 数组(JSON 字段)。"""
    stats = mod.run(db_session)
    assert stats["inserted_count"] > 0

    # 找一只有 related_sectors 的候选,验证 DB 里能完整查回
    sample = next(
        e for e in mod.CANDIDATE_FUNDS if e.get("related_sectors")
    )
    fund = db_session.get(Fund, sample["fund_code"])
    assert fund is not None
    assert fund.related_sectors == sample["related_sectors"]


def test_run_sets_fund_type_to_其他(db_session):
    """spec:全部 hardcode fund_type='其他'。"""
    mod.run(db_session)
    sample = mod.CANDIDATE_FUNDS[0]
    fund = db_session.get(Fund, sample["fund_code"])
    assert fund.fund_type == "其他"


def test_run_idempotent_second_call_inserts_zero(db_session):
    """跑两次,第二次全 skip。"""
    mod.run(db_session)
    stats2 = mod.run(db_session)
    assert stats2["inserted_count"] == 0
    assert stats2["skipped_count"] == len(mod.CANDIDATE_FUNDS)
    assert stats2["total_funds_count"] == len(mod.CANDIDATE_FUNDS)
