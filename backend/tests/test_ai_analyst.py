"""AIAnalyst 测试 — mock anthropic SDK,不发真请求。

Phase 3.9 重构后:
- 不再有 SYSTEM_PROMPT 模块常量(每个 prompts/*.py 各自有)
- 派发表 _PROMPT_MODULES: push_type → prompts module
- _build_user_prompt 移除,逻辑搬到 prompts/_common.py(测试在 test_prompts.py)
"""

from datetime import date
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from src.models import Signal
from src.models.enums import PushType
from src.prompts import close, intraday, pre_market, weekly
from src.services.ai_analyst import _FORBIDDEN_WORDS, AIAnalyst


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


def _mk_anthropic_response(text: str, in_tokens: int = 100, out_tokens: int = 200):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=in_tokens, output_tokens=out_tokens)
    return resp


# ============================================================
# 接口 / 退化路径
# ============================================================


def test_analyze_returns_empty_when_no_api_key():
    a = AIAnalyst(api_key="")
    assert a.analyze_signals([], {}) == ""


def test_no_api_key_does_not_create_client():
    a = AIAnalyst(api_key="")
    assert a.client is None


def test_client_lazy_init():
    a = AIAnalyst(api_key="sk-fake")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value = MagicMock()
        _ = a.client
        _ = a.client  # 二次访问不应再 new
    assert mock_cls.call_count == 1


# ============================================================
# 正常路径
# ============================================================


def test_analyze_returns_text_on_success():
    resp = _mk_anthropic_response("# 主线\n半导体强势 ...\n\n工具只给信号,操作你定。")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        result = a.analyze_signals(
            [_mk_signal("BK0490", "半导体", "bullish", 8, 95)], {}
        )
    assert "半导体强势" in result


def test_analyze_passes_model_and_max_tokens():
    resp = _mk_anthropic_response("ok")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client
        a = AIAnalyst(
            api_key="sk-fake", model="claude-sonnet-4-5",
            max_tokens=800, temperature=0.3,
        )
        a.analyze_signals([], {})
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-4-5"
        assert kwargs["max_tokens"] == 800
        assert kwargs["temperature"] == 0.3


# ============================================================
# Phase 3.9 — push_type 派发到对应模板
# ============================================================


@pytest.mark.parametrize(
    "push_type, expected_module",
    [
        (PushType.MORNING.value, pre_market),
        (PushType.MIDDAY.value, intraday),
        (PushType.EVENING.value, close),
        (PushType.WEEKLY.value, weekly),
    ],
)
def test_analyze_dispatches_to_correct_module(push_type, expected_module):
    """每个 push_type 应该使用对应模块的 SYSTEM_PROMPT。"""
    resp = _mk_anthropic_response("ok")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        a.analyze_signals([], {}, push_type=push_type)
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["system"] == expected_module.SYSTEM_PROMPT


def test_analyze_default_push_type_is_evening():
    """不传 push_type → 用 close (evening) 模板,保持 Phase 3.10 向后兼容。"""
    resp = _mk_anthropic_response("ok")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        a.analyze_signals([], {})  # 不传 push_type
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["system"] == close.SYSTEM_PROMPT


def test_analyze_invalid_push_type_falls_back_to_evening():
    resp = _mk_anthropic_response("ok")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        a.analyze_signals([], {}, push_type="not_a_real_type")
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["system"] == close.SYSTEM_PROMPT


# ============================================================
# 异常路径 — 任何失败返回 ""
# ============================================================


def test_analyze_returns_empty_on_api_error():
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIStatusError(
            "boom", response=MagicMock(status_code=500), body=None
        )
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        assert a.analyze_signals([], {}) == ""


def test_analyze_returns_empty_on_rate_limit():
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.RateLimitError(
            "rate limited", response=MagicMock(status_code=429), body=None
        )
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        assert a.analyze_signals([], {}) == ""


def test_analyze_returns_empty_on_unexpected_exception():
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = ValueError("unexpected")
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        assert a.analyze_signals([], {}) == ""


def test_analyze_returns_empty_on_no_text_block():
    block = MagicMock()
    block.type = "tool_use"
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=10, output_tokens=0)
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        assert a.analyze_signals([], {}) == ""


# ============================================================
# R3.1 词汇扫描
# ============================================================


@pytest.mark.parametrize(
    "text, expected",
    [
        ("建议买入 X 基金", ["买入"]),
        ("可以卖出获利", ["卖出"]),
        ("Should buy this fund", ["buy"]),
        ("hold long term", ["hold", "long"]),
        ("加仓 / 减仓 / 止盈", sorted(["加仓", "减仓", "止盈"])),
        ("半导体值得关注,留意主力动向", []),
        ("看多电池板块", []),
    ],
)
def test_check_forbidden_words(text, expected):
    assert AIAnalyst.check_forbidden_words(text) == expected


def test_forbidden_words_not_blocked_in_output():
    """命中禁用词不阻断输出,只 log warning。"""
    resp = _mk_anthropic_response("分析师建议买入半导体")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client
        a = AIAnalyst(api_key="sk-fake")
        result = a.analyze_signals([], {})
    assert "买入" in result  # 原样返回,没替换


def test_forbidden_words_list_covers_required_operation_verbs():
    """R3.1 红线词清单完整性。"""
    required = {"买入", "卖出", "做多", "做空", "止损", "止盈", "建仓", "减仓", "加仓"}
    assert required.issubset(set(_FORBIDDEN_WORDS))
    assert "持有" not in _FORBIDDEN_WORDS  # 防回归:持有作状态描述允许


def test_holding_as_state_description_not_flagged():
    text = "你持有的 [008281] 国泰CES半导体ETF联接A 可能受益于这波资金青睐"
    assert AIAnalyst.check_forbidden_words(text) == []
