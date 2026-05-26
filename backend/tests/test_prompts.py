"""Phase 3.9 — prompts/{pre_market, intraday, close, weekly}.py 测试。

包含从 test_ai_analyst.py 迁移过来的 build_user_message 测试(逻辑已挪到 _common.py)。
"""

from datetime import date

import pytest

from src.models import Signal
from src.prompts import close, intraday, pre_market, weekly
from src.prompts._common import BASE_RULES, build_user_message

ALL_MODULES = [pre_market, intraday, close, weekly]


def _mk_signal(
    sector_code: str,
    sector_name: str,
    signal_type: str,
    score: int,
    inflow_yi: float,
) -> Signal:
    return Signal(
        trade_date=date(2026, 5, 27),
        signal_type=signal_type,
        target_type="sector",
        target_code=sector_code,
        signal_name=f"{sector_name} {signal_type}",
        description="(test)",
        score_x100=score * 100,
        persistence_score=score,
        main_inflow_wan_x10000=int(inflow_yi * 10_000 * 10_000),
        meta={},
    )


# ============================================================
# 模块结构 — 每个模块都必须有 SYSTEM_PROMPT + build_prompt
# ============================================================


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_module_has_system_prompt_and_build_prompt(module):
    assert isinstance(module.SYSTEM_PROMPT, str)
    assert len(module.SYSTEM_PROMPT) > 200  # 起码包含场景指引 + BASE_RULES
    assert callable(module.build_prompt)


@pytest.mark.parametrize(
    "module, scenario_keyword",
    [
        (pre_market, "盘前简报"),
        (intraday, "盘中观察"),
        (close, "收盘复盘"),
        (weekly, "周报"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.__name__.rsplit(".", 1)[-1],
)
def test_module_system_prompt_mentions_its_scenario(module, scenario_keyword):
    assert scenario_keyword in module.SYSTEM_PROMPT


@pytest.mark.parametrize(
    "module, focus_keyword",
    [
        (pre_market, "趋势预判"),
        (intraday, "当前资金动向"),
        (close, "当日复盘"),
        (weekly, "本周主线"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.__name__.rsplit(".", 1)[-1],
)
def test_module_emphasis_keyword(module, focus_keyword):
    """每个模板有自己的"重点"差异化关键词。"""
    assert focus_keyword in module.SYSTEM_PROMPT


# ============================================================
# R3.1 — 每个模板的 SYSTEM_PROMPT 都必须明确列禁用词
# ============================================================


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_module_enforces_r31_forbidden_words(module):
    # 明确列出至少 5 个红线词,提醒 LLM
    for word in ["买入", "卖出", "做多", "做空", "建仓"]:
        assert word in module.SYSTEM_PROMPT, f"{module.__name__} 未列禁用词 {word}"


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_module_inherits_base_rules(module):
    """每个模板的 SYSTEM_PROMPT 都应拼上 BASE_RULES(R3.1 + 不给操作建议 + 格式)。"""
    # BASE_RULES 的标志性句子
    assert "严格规则(所有场景通用)" in module.SYSTEM_PROMPT
    assert "工具只给信号,操作你定" in module.SYSTEM_PROMPT


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_module_allows_holding_as_state_description(module):
    """SYSTEM_PROMPT 应说明"持有"作状态描述允许、作操作指令禁止。"""
    # BASE_RULES 里有这个澄清
    assert "你持有的 XXX" in module.SYSTEM_PROMPT or "状态描述" in module.SYSTEM_PROMPT


# ============================================================
# build_prompt — 返回非空字符串,包含数据
# ============================================================


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_build_prompt_returns_non_empty_string(module):
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    holdings = {"BK0490": [("008281", "国泰CES半导体")]}
    result = module.build_prompt(signals, holdings, None)
    assert isinstance(result, str)
    assert len(result) > 50


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_build_prompt_contains_signal_data(module):
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    holdings = {"BK0490": [("008281", "国泰CES半导体")]}
    result = module.build_prompt(signals, holdings, None)
    assert "半导体" in result
    assert "BK0490" in result
    assert "008281" in result


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_build_prompt_includes_macro_when_given(module):
    result = module.build_prompt([], {}, "美联储降息 25bp,科技股普涨")
    assert "宏观背景" in result
    assert "美联储降息" in result


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_build_prompt_omits_macro_section_when_absent(module):
    result = module.build_prompt([], {}, None)
    assert "宏观背景" not in result


# ============================================================
# _common.build_user_message — 数据 dump 的细节(从 test_ai_analyst 迁移)
# ============================================================


def test_build_user_message_filters_out_neutral_and_not_applicable():
    """neutral / not_applicable 不应进 prompt。"""
    signals = [
        _mk_signal("BK0490", "半导体", "bullish", 8, 95),
        _mk_signal("BK0900", "锂电池", "neutral", 4, 17),
    ]
    result = build_user_message(signals, {}, None)
    assert "半导体" in result
    assert "BK0490" in result
    assert "锂电池" not in result
    assert "BK0900" not in result


def test_build_user_message_truncates_long_fund_list():
    funds = [(f"00{i:04d}", f"基金{i}") for i in range(10)]
    holdings = {"BK0490": funds}
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    result = build_user_message(signals, holdings, None)
    assert "等 10 只" in result
    assert "基金0" in result and "基金3" in result
    assert "基金5" not in result  # 截在前 4


def test_build_user_message_empty_holdings():
    result = build_user_message([], {}, None)
    assert "无 A 股行业板块持仓暴露" in result


def test_build_user_message_no_actionable_signals_message():
    signals = [_mk_signal("BK0900", "锂电池", "neutral", 4, 17)]
    result = build_user_message(signals, {}, None)
    assert "无 actionable 信号" in result


def test_base_rules_constant_has_required_content():
    """BASE_RULES 必须包含 R3.1 + footer 固定句。"""
    assert "买入" in BASE_RULES
    assert "卖出" in BASE_RULES
    assert "工具只给信号,操作你定" in BASE_RULES
    assert "300-500 字" in BASE_RULES
