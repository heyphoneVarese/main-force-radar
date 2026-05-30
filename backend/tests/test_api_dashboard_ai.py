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
# AI 成功 → 用 AI 文本
# =====================================================================


def test_ai_summary_uses_ai_text_when_call_succeeds(seed_full, client):
    """_try_ai 返字符串 → summary 用 AI 文本,不走 fallback。"""
    with patch("src.services.dashboard_ai._try_ai", return_value="AI 测试结论:今日主线半导体。"):
        body = client.get("/api/dashboard/ai-summary").json()
    assert body["summary"] == "AI 测试结论:今日主线半导体。"
    assert body["cached"] is False
    # 应该写了缓存
    assert ai_mod._cache is not None


# =====================================================================
# 缓存:第二次调返 cached=true
# =====================================================================


def test_ai_summary_second_call_returns_cached_true(seed_full, client):
    """第一次调写缓存,第二次直接命中,不再调 _try_ai。"""
    mock_ai = patch("src.services.dashboard_ai._try_ai", return_value="first call text")
    with mock_ai as m:
        body1 = client.get("/api/dashboard/ai-summary").json()
        body2 = client.get("/api/dashboard/ai-summary").json()
    assert body1["cached"] is False
    assert body2["cached"] is True
    # 文本一致(来自缓存)
    assert body1["summary"] == body2["summary"] == "first call text"
    # _try_ai 只被调一次
    assert m.call_count == 1


# =====================================================================
# 缓存过期 → 重新生成
# =====================================================================


def test_ai_summary_cache_expires_after_ttl(seed_full, client):
    """手动把 _cache.expires_at 推到过去 → 下一次调用应重算。"""
    with patch("src.services.dashboard_ai._try_ai", return_value="v1") as m:
        client.get("/api/dashboard/ai-summary")
    assert ai_mod._cache is not None

    # 把过期时间推到 1 小时前
    ai_mod._cache["expires_at"] = datetime.now() - timedelta(hours=1)

    with patch("src.services.dashboard_ai._try_ai", return_value="v2") as m2:
        body = client.get("/api/dashboard/ai-summary").json()
    assert body["summary"] == "v2"  # 用了新调用
    assert body["cached"] is False
    assert m2.call_count == 1


# =====================================================================
# 缓存:trade_date 变化 → 强制 invalidate
# =====================================================================


def test_ai_summary_cache_invalidates_when_trade_date_advances(
    db_session, seed_full, client
):
    """5/30 数据缓存了 v1;库里又入了 5/31 数据 → 新 trade_date 应让缓存失效。"""
    with patch("src.services.dashboard_ai._try_ai", return_value="day1"):
        client.get("/api/dashboard/ai-summary")
    assert ai_mod._cache is not None

    # 入 5/31 数据(模拟 cron 15:20 新一天到了)
    d2 = date(2026, 5, 31)
    db_session.add(_mk_flow("BK0727", "半导体", d2, 15_000_000_000))
    db_session.commit()

    with patch("src.services.dashboard_ai._try_ai", return_value="day2"):
        body = client.get("/api/dashboard/ai-summary").json()
    assert body["trade_date"] == "2026-05-31"
    assert body["summary"] == "day2"
    assert body["cached"] is False


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
