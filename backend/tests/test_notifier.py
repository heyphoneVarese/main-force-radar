"""ServerChanNotifier 测试 — mock httpx,不发真请求。"""

from datetime import date
from unittest.mock import MagicMock, patch

import httpx

from src.models import Signal
from src.models.enums import SignalType
from src.services.notifier import ServerChanNotifier


# ============================================================
# 发送层 send()
# ============================================================


def _patch_httpx_post(status_code=200, json_data=None, raise_exc=None):
    """构造一个 patch context,模拟 httpx.Client().__enter__().post()。"""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json.return_value = json_data
    mock_resp.text = "(mocked)"

    mock_client = MagicMock()
    if raise_exc is not None:
        mock_client.__enter__.return_value.post.side_effect = raise_exc
    else:
        mock_client.__enter__.return_value.post.return_value = mock_resp

    return patch("src.services.notifier.httpx.Client", return_value=mock_client)


def test_send_success_code_zero():
    with _patch_httpx_post(200, {"code": 0, "message": "ok"}):
        n = ServerChanNotifier("test_sckey_123")
        assert n.send("title", "content") is True


def test_send_failure_nonzero_code():
    with _patch_httpx_post(200, {"code": 40001, "message": "key 错"}):
        n = ServerChanNotifier("bad_key")
        assert n.send("title", "content") is False


def test_send_failure_http_status_500():
    with _patch_httpx_post(500, {}):
        n = ServerChanNotifier("test")
        assert n.send("title", "content") is False


def test_send_failure_network_error():
    with _patch_httpx_post(raise_exc=httpx.ConnectError("network down")):
        n = ServerChanNotifier("test")
        assert n.send("title", "content") is False


def test_send_empty_sckey_returns_false_without_request():
    """sckey 空时直接返回 False,不发请求。"""
    n = ServerChanNotifier("")
    # 即便没 mock httpx 也不应抛
    assert n.send("title", "content") is False


def test_send_non_json_response():
    """body 不是 JSON,异常吞掉返回 False。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("not json")
    mock_resp.text = "<html>error page</html>"
    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.return_value = mock_resp
    with patch("src.services.notifier.httpx.Client", return_value=mock_client):
        assert ServerChanNotifier("x").send("a", "b") is False


# ============================================================
# Markdown 渲染 build_summary_markdown()
# ============================================================


def _mk_signal(
    sector_code: str,
    sector_name: str,
    signal_type: str,
    score: int,
    inflow_yi: float,
    trade_date: date = date(2026, 5, 27),
) -> Signal:
    return Signal(
        trade_date=trade_date,
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


def test_markdown_title_uses_as_of_date():
    title, _ = ServerChanNotifier.build_summary_markdown(
        signals=[], as_of=date(2026, 5, 27)
    )
    assert "2026-05-27" in title
    assert "📊" in title and "主力风向标" in title


def test_markdown_renders_all_three_sections():
    signals = [
        _mk_signal("BK0490", "半导体", "bullish", 8, 95),
        _mk_signal("BK0727", "5G概念", "bearish", 9, -150),
        _mk_signal("BK1019", "人工智能", "warning", 6, -40),
    ]
    _, content = ServerChanNotifier.build_summary_markdown(
        signals, holdings_by_sector={}, as_of=date(2026, 5, 27)
    )
    assert "看多 (1)" in content
    assert "看空 (1)" in content
    assert "警告 (1)" in content
    assert "半导体" in content and "BK0490" in content
    assert "5G概念" in content and "BK0727" in content
    assert "人工智能" in content and "BK1019" in content


def test_markdown_includes_holding_funds():
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    holdings = {
        "BK0490": [("008281", "国泰CES半导体ETF联接A"), ("014320", "德邦半导体产业")],
    }
    _, content = ServerChanNotifier.build_summary_markdown(
        signals, holdings, as_of=date(2026, 5, 27)
    )
    assert "你持仓 2 只" in content
    assert "国泰CES半导体ETF联接A" in content
    assert "德邦半导体产业" in content


def test_markdown_truncates_long_fund_list():
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    funds = [(f"00{i:04d}", f"基金{i}") for i in range(11)]
    holdings = {"BK0490": funds}
    _, content = ServerChanNotifier.build_summary_markdown(
        signals, holdings, as_of=date(2026, 5, 27)
    )
    assert "你持仓 11 只" in content
    assert "等 11 只" in content  # 截断后缀
    # 前 4 个名字应该出现
    assert "基金0" in content
    assert "基金3" in content
    # 第 5 个不应出现
    assert "基金5" not in content


def test_markdown_annotations_strong_signals():
    bullish_strong = _mk_signal("BK0490", "半导体", "bullish", 8, 95)
    bearish_strong = _mk_signal("BK0727", "5G概念", "bearish", 9, -150)
    bullish_normal = _mk_signal("BK1144", "光模块", "bullish", 6, 31)
    bearish_normal = _mk_signal("BK0478", "光伏设备", "bearish", 5, -29)
    warning_sig = _mk_signal("BK1019", "人工智能", "warning", 6, -40)

    _, content = ServerChanNotifier.build_summary_markdown(
        [bullish_strong, bearish_strong, bullish_normal, bearish_normal, warning_sig],
        as_of=date(2026, 5, 27),
    )
    # 强信号 / 强退潮 / 价量背离 — annotations 加 *斜体*
    assert "*强信号*" in content
    assert "*强退潮*" in content
    assert "*价量背离*" in content
    # 普通 bullish / bearish 不加注解(score 6 不算强)
    assert content.count("*强信号*") == 1  # 只有 score 8 的一条
    assert content.count("*强退潮*") == 1


def test_markdown_empty_signals_shows_no_signal_message():
    _, content = ServerChanNotifier.build_summary_markdown(
        signals=[], as_of=date(2026, 5, 27)
    )
    assert "无板块级信号" in content
    assert "看多 0" in content


def test_markdown_filters_out_neutral_and_not_applicable():
    """neutral 和 not_applicable 不进推送内容(只看 actionable 三类)。"""
    signals = [
        _mk_signal("BK0490", "半导体", "bullish", 8, 95),
        _mk_signal("BK0900", "锂电池", "neutral", 4, 17),
        # not_applicable 一般不会进 signals 表,但防御性测一下
    ]
    _, content = ServerChanNotifier.build_summary_markdown(
        signals, holdings_by_sector={}, as_of=date(2026, 5, 27)
    )
    assert "锂电池" not in content
    assert "BK0900" not in content


def test_markdown_sorts_by_score_desc():
    signals = [
        _mk_signal("BK0001", "A", "bullish", 6, 30),
        _mk_signal("BK0002", "B", "bullish", 9, 200),
        _mk_signal("BK0003", "C", "bullish", 7, 60),
    ]
    _, content = ServerChanNotifier.build_summary_markdown(
        signals, as_of=date(2026, 5, 27)
    )
    # B (score 9) 出现在 A (score 6) 之前
    idx_a = content.find("**A**")
    idx_b = content.find("**B**")
    idx_c = content.find("**C**")
    assert idx_b < idx_c < idx_a, "应按 score 降序排"


def test_markdown_includes_ai_analysis_when_provided():
    """Phase 3.10: 传 ai_analysis 应渲染「🤖 AI 分析师视角」段在最前。"""
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    ai_text = "## 主线\n今日半导体强势 ...\n\n工具只给信号,操作你定。"
    _, content = ServerChanNotifier.build_summary_markdown(
        signals, ai_analysis=ai_text, as_of=date(2026, 5, 27)
    )
    assert "🤖 AI 分析师视角" in content
    assert "今日半导体强势" in content
    # AI 段应该排在信号段之前
    assert content.index("🤖") < content.index("今日板块信号")


def test_markdown_no_ai_section_when_ai_analysis_empty():
    """ai_analysis 为空字符串/None → 不渲染 AI 段(向后兼容)。"""
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    _, content_empty = ServerChanNotifier.build_summary_markdown(
        signals, ai_analysis="", as_of=date(2026, 5, 27)
    )
    _, content_none = ServerChanNotifier.build_summary_markdown(
        signals, ai_analysis=None, as_of=date(2026, 5, 27)
    )
    assert "🤖" not in content_empty
    assert "🤖" not in content_none
    # 仍然有信号段
    assert "半导体" in content_empty


def test_markdown_no_ai_section_when_only_whitespace():
    """空白字符串应视同未提供。"""
    _, content = ServerChanNotifier.build_summary_markdown(
        signals=[_mk_signal("BK0490", "半导体", "bullish", 8, 95)],
        ai_analysis="   \n  \n  ",
        as_of=date(2026, 5, 27),
    )
    assert "🤖" not in content


def test_markdown_footer_present():
    _, content = ServerChanNotifier.build_summary_markdown(
        signals=[_mk_signal("BK0490", "半导体", "bullish", 8, 95)],
        as_of=date(2026, 5, 27),
    )
    assert "工具只给信号,操作你定" in content


# ============================================================
# send_signal_summary 集成 (mock send)
# ============================================================


def test_send_signal_summary_calls_send_with_built_markdown():
    signals = [_mk_signal("BK0490", "半导体", "bullish", 8, 95)]
    n = ServerChanNotifier("x")
    with patch.object(n, "send", return_value=True) as mock_send:
        result = n.send_signal_summary(signals, holdings_by_sector={}, as_of=date(2026, 5, 27))
    assert result is True
    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    title, content = args
    assert "2026-05-27" in title
    assert "半导体" in content
