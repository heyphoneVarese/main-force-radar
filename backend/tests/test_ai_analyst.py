"""AIAnalyst 测试 — mock anthropic SDK,不发真请求。"""

from datetime import date
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from src.models import Signal
from src.services.ai_analyst import _FORBIDDEN_WORDS, SYSTEM_PROMPT, AIAnalyst


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
    """构造一个 anthropic.Message 风格的 mock。"""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=in_tokens, output_tokens=out_tokens)
    return resp


# ============================================================
# 接口/退化路径
# ============================================================


def test_analyze_returns_empty_when_no_api_key():
    a = AIAnalyst(api_key="")
    assert a.analyze_signals([], {}) == ""


def test_no_api_key_does_not_create_client():
    a = AIAnalyst(api_key="")
    assert a.client is None
    # 二次访问也不应实例化
    assert a.client is None


def test_client_lazy_init():
    a = AIAnalyst(api_key="sk-fake")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value = MagicMock()
        _ = a.client
        _ = a.client  # 第二次不应再 new
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
    assert "工具只给信号" in result


def test_analyze_passes_model_and_system_prompt():
    resp = _mk_anthropic_response("ok")
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = resp
        mock_cls.return_value = mock_client

        a = AIAnalyst(api_key="sk-fake", model="claude-sonnet-4-5",
                       max_tokens=800, temperature=0.3)
        a.analyze_signals([], {})

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-4-5"
        assert kwargs["max_tokens"] == 800
        assert kwargs["temperature"] == 0.3
        assert kwargs["system"] == SYSTEM_PROMPT


# ============================================================
# user prompt 构造
# ============================================================


def test_user_prompt_includes_signals_and_holdings():
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    holdings = {"BK0490": [("008281", "国泰CES半导体")]}
    prompt = AIAnalyst._build_user_prompt(signals, holdings, None)

    assert "半导体" in prompt
    assert "BK0490" in prompt
    assert "008281" in prompt
    assert "国泰CES半导体" in prompt
    # 无 macro 时不应出现段标
    assert "宏观背景" not in prompt


def test_user_prompt_includes_macro_when_provided():
    prompt = AIAnalyst._build_user_prompt([], {}, "美联储降息 25bp,科技股普涨")
    assert "宏观背景" in prompt
    assert "美联储降息" in prompt


def test_user_prompt_filters_out_neutral_and_not_applicable():
    """neutral / not_applicable 不应进 prompt(节省 token + 降噪)。"""
    signals = [
        _mk_signal("BK0490", "半导体", "bullish", 8, 95),
        _mk_signal("BK0900", "锂电池", "neutral", 4, 17),
    ]
    prompt = AIAnalyst._build_user_prompt(signals, {}, None)
    assert "半导体" in prompt
    assert "BK0490" in prompt
    assert "锂电池" not in prompt
    assert "BK0900" not in prompt


def test_user_prompt_truncates_long_fund_list():
    funds = [(f"00{i:04d}", f"基金{i}") for i in range(10)]
    holdings = {"BK0490": funds}
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    prompt = AIAnalyst._build_user_prompt(signals, holdings, None)
    assert "等 10 只" in prompt
    assert "基金0" in prompt
    assert "基金3" in prompt
    # 第 5 个之后被截
    assert "基金5" not in prompt


def test_user_prompt_empty_holdings():
    prompt = AIAnalyst._build_user_prompt([], {}, None)
    assert "无 A 股行业板块持仓暴露" in prompt


def test_user_prompt_no_actionable_signals():
    signals = [_mk_signal("BK0900", "锂电池", "neutral", 4, 17)]
    prompt = AIAnalyst._build_user_prompt(signals, {}, None)
    assert "无 actionable 信号" in prompt


# ============================================================
# 异常路径 — 任何失败返回 ""
# ============================================================


def test_analyze_returns_empty_on_api_error():
    with patch("src.services.ai_analyst.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        # 构造一个 APIStatusError(anthropic.APIError 的子类)
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
    """响应里只有 tool_use 等其他 block,无 text block。"""
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

    # 文本原样返回(没替换、没过滤)
    assert "买入" in result
    assert result == "分析师建议买入半导体"


def test_forbidden_words_list_covers_required_operation_verbs():
    """R3.1 红线词清单完整性 — 操作指令动词必须全覆盖。

    注:'持有'被显式移除(误报率高:'你持有的 XXX' 是状态描述,非操作指令)。
    SYSTEM_PROMPT 里仍约束'建议持有/应该持有'等组合,由 prompt 守门。
    """
    required_operation_verbs = {
        "买入", "卖出", "做多", "做空",
        "止损", "止盈", "建仓", "减仓", "加仓",
    }
    assert required_operation_verbs.issubset(set(_FORBIDDEN_WORDS))
    # 显式断言「持有」不在禁用词列表(误报防回归)
    assert "持有" not in _FORBIDDEN_WORDS


def test_holding_as_state_description_not_flagged():
    """'你持有的 XXX 基金' 是状态描述,不应被 R3.1 扫描命中。"""
    text = "你持有的 [008281] 国泰CES半导体ETF联接A 可能受益于这波资金青睐"
    assert AIAnalyst.check_forbidden_words(text) == []
