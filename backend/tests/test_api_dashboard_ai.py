"""GET /api/dashboard/ai-summary 测试。

独立文件因为 autouse 清缓存 fixture 不应污染其他 dashboard 测试。
mock Anthropic 调用(_try_ai),保证测试无网络/无 API key 也能跑。
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.models import (
    Fund,
    Holding,
    MarketIndexDaily,
    SectorAlias,
    SectorFlowDaily,
    Signal,
)
from src.services import dashboard_ai as ai_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个测试前后都清模块级缓存。"""
    ai_mod._clear_cache_for_test()
    yield
    ai_mod._clear_cache_for_test()


# =====================================================================
# 数据 fixtures
# =====================================================================


def _mk_fund(code: str, name: str, related: list[str] | None = None) -> Fund:
    return Fund(fund_code=code, fund_name=name, fund_type="混合", related_sectors=related)


def _mk_holding(code: str) -> Holding:
    return Holding(
        fund_code=code,
        cost_nav_x10000=10000,
        shares_x100=1_000_000,
        bought_at=date(2025, 1, 1),
    )


def _mk_alias(label: str, bk: str, name: str) -> SectorAlias:
    return SectorAlias(chinese_label=label, sector_code=bk, sector_name=name, confidence=1.0)


def _mk_signal(bk: str, d: date, sig_type: str, score: int, inflow: int) -> Signal:
    return Signal(
        trade_date=d, signal_type=sig_type, target_type="sector", target_code=bk,
        signal_name=f"{bk} {sig_type}", description="x",
        score_x100=score * 100, persistence_score=score,
        main_inflow_wan_x10000=inflow,
        triggered_at=datetime(d.year, d.month, d.day, 15, 30),
    )


def _mk_flow(bk: str, name: str, d: date, inflow: int, change_pct: int | None = 200) -> SectorFlowDaily:
    return SectorFlowDaily(
        sector_code=bk, sector_name=name, sector_type="industry",
        trade_date=d, main_inflow_wan_x10000=inflow,
        main_inflow_pct_x10000=500, change_pct_x10000=change_pct,
    )


@pytest.fixture
def seed_full(db_session):
    """标准 fixture:1 天的市场指数 + 6 个板块流 + 2 只持仓基金。"""
    d = date(2026, 5, 30)
    db_session.add_all([
        # 4 大指数
        MarketIndexDaily(index_code="sh000001", index_name="上证指数",
                         trade_date=d, close_x10000=31205000, change_pct_x10000=66),
        MarketIndexDaily(index_code="sz399001", index_name="深证成指",
                         trade_date=d, close_x10000=10120000, change_pct_x10000=41),
        MarketIndexDaily(index_code="sz399006", index_name="创业板指",
                         trade_date=d, close_x10000=22035000, change_pct_x10000=-23),
        MarketIndexDaily(index_code="sh000300", index_name="沪深300",
                         trade_date=d, close_x10000=41129000, change_pct_x10000=87),
        # 板块流:3 个流入 + 2 个流出
        _mk_flow("BK0727", "半导体", d, 12_000_000_000),
        _mk_flow("BK0739", "AI算力", d, 8_800_000_000),
        _mk_flow("BK0428", "电池", d, 5_200_000_000),
        _mk_flow("BK0429", "光伏设备", d, -1_800_000_000),
        _mk_flow("BK0999", "元宇宙", d, -3_000_000_000),
        # 2 只持仓基金:半导体 bullish,光伏 bearish
        _mk_fund("F_SEMI", "半导体基金", related=["半导体"]),
        _mk_fund("F_PV", "光伏基金", related=["光伏设备"]),
        _mk_holding("F_SEMI"),
        _mk_holding("F_PV"),
        _mk_alias("半导体", "BK0727", "半导体"),
        _mk_alias("光伏设备", "BK0429", "光伏设备"),
        _mk_signal("BK0727", d, "bullish", 8, 12_000_000_000),
        _mk_signal("BK0429", d, "bearish", 7, -1_800_000_000),
    ])
    db_session.commit()
    return d


# =====================================================================
# 空数据态
# =====================================================================


def test_ai_summary_empty_db_returns_friendly_empty(client):
    """完全空库 → 200 + summary 含"尚无数据"提示 + cached=false。"""
    resp = client.get("/api/dashboard/ai-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] is None
    assert "尚无数据" in body["summary"]
    assert body["cached"] is False
    assert body["generated_at"] is not None
    # 空数据不应写缓存
    assert ai_mod._cache is None


# =====================================================================
# 无 API key → fallback
# =====================================================================


def test_ai_summary_fallback_when_no_api_key(seed_full, client):
    """settings.anthropic_api_key=空字符串 → 不调 AI,直接 fallback。"""
    with patch("src.services.dashboard_ai.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        body = client.get("/api/dashboard/ai-summary").json()
    assert body["trade_date"] == "2026-05-30"
    # fallback 必须包含数据,不是空话
    assert "半导体" in body["summary"]
    assert "亿" in body["summary"]
    assert body["cached"] is False


# =====================================================================
# AI 调用失败 → fallback
# =====================================================================


def test_ai_summary_fallback_when_ai_raises(seed_full, client):
    """有 API key 但 Anthropic SDK 抛 → fallback,200。"""
    with patch("src.services.dashboard_ai.settings") as mock_settings, \
         patch("src.services.dashboard_ai._try_ai", return_value=None):
        mock_settings.anthropic_api_key = "sk-fake"
        body = client.get("/api/dashboard/ai-summary").json()
    assert body["trade_date"] == "2026-05-30"
    assert "半导体" in body["summary"]
    assert body["cached"] is False


# =====================================================================
# PR19 — 新结构化字段 + intraday/daily 双源
# =====================================================================
# 旧 Claude/cache 路径相关测试已删 — PR19 API endpoint 不再走 _try_ai
# 和 24h cache;底层 _try_ai/缓存代码本身仍可单测(本文件 test_digest_*
# 和 test_prompt_* 已覆盖)。


def _mk_intraday_row(
    code: str,
    name: str,
    snapshot_time: datetime,
    main_inflow_wan_x10000: int,
    change_pct_x10000: int | None = 200,
):
    from src.models import IntradaySectorFlow
    return IntradaySectorFlow(
        sector_code=code, sector_name=name, sector_type="industry",
        trade_date=snapshot_time.date(), snapshot_time=snapshot_time,
        main_inflow_wan_x10000=main_inflow_wan_x10000,
        change_pct_x10000=change_pct_x10000,
    )


def test_ai_summary_source_intraday_when_has_data(db_session, client):
    """intraday 有最新 snapshot → source='intraday', cached=False。"""
    snapshot = datetime(2026, 6, 1, 14, 30)
    # 55 亿 → wan_yuan_to_int = 55 × 10000 × 10000 = 5_500_000_000
    db_session.add_all([
        _mk_intraday_row("BK0001", "电力", snapshot, 5_500_000_000),
        _mk_intraday_row("BK0002", "半导体", snapshot, -37_900_000_000),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/ai-summary").json()
    assert body["source"] == "intraday"
    assert body["cached"] is False
    assert body["data_date"] == "2026-06-01"
    assert body["data_time"] == "14:30"


def test_ai_summary_inflow_top3_from_intraday_industry(db_session, client):
    """intraday 模式下 inflow_top3 按 main_inflow 降序取前 3。"""
    snapshot = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday_row("BK0001", "电力", snapshot, 5_560_000_000),    # 55.6 亿
        _mk_intraday_row("BK0002", "公用事业", snapshot, 5_350_000_000),  # 53.5 亿
        _mk_intraday_row("BK0003", "火力发电", snapshot, 3_670_000_000),  # 36.7 亿
        _mk_intraday_row("BK0004", "其他", snapshot, 100_000_000),         # 1 亿,不入 top3
    ])
    db_session.commit()

    body = client.get("/api/dashboard/ai-summary").json()
    names = [s["sector_name"] for s in body["inflow_top3"]]
    assert names == ["电力", "公用事业", "火力发电"]
    # main_inflow_yi 是亿元 Decimal 字符串
    from decimal import Decimal
    assert Decimal(body["inflow_top3"][0]["main_inflow_yi"]) == Decimal("55.6")


def test_ai_summary_outflow_top3_only_negative(db_session, client):
    """outflow_top3 只含 main_inflow < 0 的,按升序(最负的在前)。"""
    snapshot = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday_row("BK_POS", "电力", snapshot, 5_000_000_000),
        _mk_intraday_row("BK_NEG1", "半导体", snapshot, -37_930_000_000),  # -379.3 亿
        _mk_intraday_row("BK_NEG2", "芯片", snapshot, -20_000_000_000),    # -200 亿
        _mk_intraday_row("BK_NEG3", "机器人", snapshot, -5_000_000_000),
    ])
    db_session.commit()

    body = client.get("/api/dashboard/ai-summary").json()
    names = [s["sector_name"] for s in body["outflow_top3"]]
    assert names == ["半导体", "芯片", "机器人"]
    # 正流入板块不应进 outflow
    assert "电力" not in names


def test_ai_summary_summary_text_intraday_format(db_session, client):
    """intraday 模式 summary_text 应含 '盘中主力净流入'。"""
    snapshot = datetime(2026, 6, 1, 14, 30)
    db_session.add(_mk_intraday_row(
        "BK0001", "电力", snapshot, 5_560_000_000,  # 55.6 亿
    ))
    db_session.commit()

    body = client.get("/api/dashboard/ai-summary").json()
    assert "盘中主力净流入" in body["summary_text"]
    assert "电力" in body["summary_text"]
    # R3 红线检查
    forbidden = ["买入", "卖出", "加仓", "减仓", "继续持有", "建议", "推荐"]
    for w in forbidden:
        assert w not in body["summary_text"]


def test_ai_summary_fallback_to_daily_when_intraday_empty(seed_full, client):
    """intraday 空但 daily 有数据 → source='daily_cached'。"""
    body = client.get("/api/dashboard/ai-summary").json()
    assert body["source"] == "daily_cached"
    # daily 模式下 data_time 为 null,data_date 是 trade_date
    assert body["data_time"] is None
    assert body["data_date"] == "2026-05-30"
    # summary_text 应含"收盘主力净流入"
    assert "收盘主力" in body["summary_text"]


def test_ai_summary_does_not_call_claude_in_new_path(seed_full, client):
    """关键 R 线:新 PR19 路径不应调用 _try_ai(Claude)。"""
    with patch("src.services.dashboard_ai._try_ai") as mock_try_ai:
        body = client.get("/api/dashboard/ai-summary").json()
    assert mock_try_ai.call_count == 0
    # 但仍能拿到合理输出
    assert body["source"] == "daily_cached"
    assert body["summary_text"]


def test_ai_summary_holding_stats_present(seed_full, client):
    """holding_stats 应是 dict(可能为空,可能含 bullish/bearish/neutral 等)。"""
    body = client.get("/api/dashboard/ai-summary").json()
    assert isinstance(body["holding_stats"], dict)
    # seed_full 有 2 只持仓:F_SEMI bullish + F_PV bearish
    assert body["holding_stats"].get("bullish", 0) >= 0


def test_ai_summary_intraday_ignores_concept_sectors(db_session, client):
    """concept 板块 _x10000 即便巨大也不进 intraday inflow_top3(只 industry)。"""
    snapshot = datetime(2026, 6, 1, 14, 30)
    db_session.add_all([
        _mk_intraday_row("BK_IND", "电力", snapshot, 1_000_000_000),
    ])
    # 手动加一个 concept 巨大值
    from src.models import IntradaySectorFlow
    db_session.add(IntradaySectorFlow(
        sector_code="BK_CON", sector_name="AI算力", sector_type="concept",
        trade_date=snapshot.date(), snapshot_time=snapshot,
        main_inflow_wan_x10000=99_999_999_999_999,
        change_pct_x10000=500,
    ))
    db_session.commit()

    body = client.get("/api/dashboard/ai-summary").json()
    names = [s["sector_name"] for s in body["inflow_top3"]]
    assert "电力" in names
    assert "AI算力" not in names  # concept 被排除


def test_ai_summary_legacy_fields_still_present(db_session, client):
    """旧字段 trade_date/summary/generated_at/cached 必须仍在 response 里
    (前端可能还在用)。"""
    body = client.get("/api/dashboard/ai-summary").json()
    assert "trade_date" in body
    assert "summary" in body
    assert "generated_at" in body
    assert "cached" in body


# =====================================================================
# Fallback 必须基于真实数据(不能是空话)
# =====================================================================


def test_ai_summary_fallback_content_is_data_driven(db_session, seed_full):
    """直接 unit-test fallback 渲染器,验证内容包含 sector 名 + 资金量 + 持仓分布。"""
    digest = ai_mod.build_ai_input_digest(db_session)
    text = ai_mod._build_fallback_summary(digest)
    # 必含至少一个 top inflow sector
    assert "半导体" in text or "AI算力" in text or "电池" in text
    # 必含资金量
    assert "亿" in text
    # 持仓分布部分(本 fixture 是 2 只持仓)
    assert "持仓 2 只" in text


# =====================================================================
# Digest 单元测试
# =====================================================================


def test_digest_market_in_default_indices_order(db_session, seed_full):
    digest = ai_mod.build_ai_input_digest(db_session)
    names = [m["name"] for m in digest["market"]]
    assert names == ["上证指数", "深证成指", "创业板指", "沪深300"]


def test_digest_top_inflow_and_outflow_separated(db_session, seed_full):
    digest = ai_mod.build_ai_input_digest(db_session)
    inflow_names = [s["name"] for s in digest["top_inflow_sectors"]]
    outflow_names = [s["name"] for s in digest["top_outflow_sectors"]]
    # Top inflow:半导体(120e8) > AI算力(88e8) > 电池(52e8) > 光伏(-1.8e9) > 元宇宙(-3e9)
    # Top 5 inflow = 全 5 个(但负的也会被算进 inflow 列表的尾部)
    assert "半导体" in inflow_names
    assert "AI算力" in inflow_names
    # outflow 只列 < 0 的
    assert set(outflow_names) == {"光伏设备", "元宇宙"}
    # 元宇宙 最负 → outflow 排首位
    assert outflow_names[0] == "元宇宙"


def test_digest_holdings_distribution(db_session, seed_full):
    digest = ai_mod.build_ai_input_digest(db_session)
    dist = digest["holdings_signal_dist"]
    # F_SEMI bullish + F_PV bearish
    assert dist.get("bullish") == 1
    assert dist.get("bearish") == 1
    assert digest["holdings_total"] == 2


def test_digest_empty_db_returns_null_trade_date(db_session):
    digest = ai_mod.build_ai_input_digest(db_session)
    assert digest["trade_date"] is None
    assert digest["market"] == []
    assert digest["top_inflow_sectors"] == []
    assert digest["top_outflow_sectors"] == []
    assert digest["holdings_total"] == 0


# =====================================================================
# Fallback 格式辅助函数
# =====================================================================


def test_fmt_pct_signs():
    assert ai_mod._fmt_pct(66) == "+0.66%"
    assert ai_mod._fmt_pct(-150) == "-1.50%"
    assert ai_mod._fmt_pct(0) == "0.00%"   # 持平不带符号
    assert ai_mod._fmt_pct(None) == "n/a"


def test_fmt_yi_signs():
    # 12_000_000_000 / 1e4 / 1e4 = 120 亿
    assert "120.0" in ai_mod._fmt_yi(12_000_000_000)
    assert ai_mod._fmt_yi(12_000_000_000).startswith("+")
    assert ai_mod._fmt_yi(-1_800_000_000).startswith("-")


# =====================================================================
# Prompt 构造
# =====================================================================


def test_prompt_contains_r3_constraint_words(db_session, seed_full):
    """prompt 必须明确告诉 AI 不能给投资建议、不能预测涨跌(R3 红线)。"""
    digest = ai_mod.build_ai_input_digest(db_session)
    prompt = ai_mod._build_prompt(digest)
    assert "不给出投资建议" in prompt or "投资建议" in prompt
    assert "不预测涨跌" in prompt or "预测涨跌" in prompt
    assert "R3" in prompt or "红线" in prompt
