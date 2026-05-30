"""Dashboard AI 一句话结论(Phase 5.1 PR5)。

设计要点:
- 24h TTL 模块级内存缓存(R6:单用户单实例,不上 Redis)
- 缓存键不显式;但缓存值的 trade_date 跟当前最新 trade_date 比对,
  若不一致(15:20 cron 拉到新数据)→ invalidate 强制重算
- API key 缺失 / Anthropic 调用失败 / 任何异常 → 退回 fallback,
  fallback 基于真实 digest 数据生成(不是空话)
- digest 编排:已有 dashboard service 全部产出 _x10000 整数,本模块
  在这里转 万元/亿/百分数,只为给 AI 看(R1 不松绑,只是输出格式化)

R 线兼容:不写任何表;只读 market_index_daily / sector_flow_daily,
以及通过 services/dashboard_holdings 间接读 holdings/signals。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import settings
from src.models import MarketIndexDaily, SectorFlowDaily
from src.services.dashboard_holdings import build_holdings_summary
from src.services.data_fetcher import DEFAULT_INDICES
from src.utils.date_helper import cn_now

logger = logging.getLogger(__name__)

# =====================================================================
# 缓存(模块级,进程内单例;FastAPI 单 worker 即足够,R4 单用户)
# =====================================================================
_TTL_SECONDS = 24 * 60 * 60  # 24h
_cache: dict[str, Any] | None = None


def _clear_cache_for_test() -> None:
    """ONLY for test isolation。不要在生产代码里调用。"""
    global _cache
    _cache = None


# 模型 / token 上限:跟 ai_analyst 同口径,但更短(dashboard 一句话)
_AI_MODEL = "claude-sonnet-4-5"
_AI_MAX_TOKENS = 200
# 每端各取 5 个,够 AI 看清主线 + outflow
_DIGEST_TOP_N = 5


# =====================================================================
# digest:把 4 个 dashboard 数据源压缩成给 AI 看的小 dict
# =====================================================================


def build_ai_input_digest(
    session: Session, latest_date: date | None = None
) -> dict[str, Any]:
    """构造 AI 输入(也是 fallback 渲染的数据源)。

    Returns:
        {
          "trade_date": date | None,
          "market": [{"name": "上证指数", "change_pct_x10000": int}, ...],
          "top_inflow_sectors": [{"name": "半导体", "wan_x10000": int}, ...],
          "top_outflow_sectors": [{"name": "光伏设备", "wan_x10000": int}, ...],
          "holdings_signal_dist": {"bullish": int, "bearish": int, ...},
          "holdings_total": int,
        }
    """
    if latest_date is None:
        latest_date = session.scalar(
            select(SectorFlowDaily.trade_date)
            .order_by(SectorFlowDaily.trade_date.desc())
            .limit(1)
        )

    # market:DEFAULT_INDICES 顺序
    market_rows = (
        list(session.scalars(
            select(MarketIndexDaily).where(
                MarketIndexDaily.trade_date == (
                    session.scalar(
                        select(MarketIndexDaily.trade_date)
                        .order_by(MarketIndexDaily.trade_date.desc())
                        .limit(1)
                    )
                )
            )
        ))
        if latest_date is not None
        else []
    )
    order_map = {c: i for i, (c, _) in enumerate(DEFAULT_INDICES)}
    market_rows.sort(key=lambda r: order_map.get(r.index_code, len(DEFAULT_INDICES)))
    market = [
        {"name": r.index_name, "change_pct_x10000": r.change_pct_x10000}
        for r in market_rows
    ]

    # sectors:取 latest_date 的 Top inflow / Top outflow
    top_inflow: list[dict[str, Any]] = []
    top_outflow: list[dict[str, Any]] = []
    if latest_date is not None:
        all_flows = list(session.scalars(
            select(SectorFlowDaily)
            .where(SectorFlowDaily.trade_date == latest_date)
            .order_by(SectorFlowDaily.main_inflow_wan_x10000.desc())
        ))
        top_inflow = [
            {"name": r.sector_name, "wan_x10000": r.main_inflow_wan_x10000}
            for r in all_flows[:_DIGEST_TOP_N]
        ]
        # outflow = 升序前 N(最负的)
        outflow_sorted = sorted(
            all_flows, key=lambda r: r.main_inflow_wan_x10000
        )
        top_outflow = [
            {"name": r.sector_name, "wan_x10000": r.main_inflow_wan_x10000}
            for r in outflow_sorted[:_DIGEST_TOP_N]
            if r.main_inflow_wan_x10000 < 0
        ]

    # holdings 信号分布
    summary = build_holdings_summary(session)
    dist: dict[str, int] = {}
    for h in summary["holdings"]:
        dist[h["signal_type"]] = dist.get(h["signal_type"], 0) + 1

    return {
        "trade_date": latest_date,
        "market": market,
        "top_inflow_sectors": top_inflow,
        "top_outflow_sectors": top_outflow,
        "holdings_signal_dist": dist,
        "holdings_total": len(summary["holdings"]),
    }


# =====================================================================
# 格式化辅助
# =====================================================================


def _fmt_pct(x10000: int | None) -> str:
    """66 → '+0.66%';-150 → '-1.50%';None → 'n/a'"""
    if x10000 is None:
        return "n/a"
    sign = "+" if x10000 > 0 else ("" if x10000 == 0 else "-")
    return f"{sign}{abs(x10000) / 100:.2f}%"


def _fmt_yi(wan_x10000: int) -> str:
    """主力净流入万元 _x10000 → '120.0 亿' / '-18.0 亿'。"""
    yi = wan_x10000 / 10_000 / 10_000
    sign = "+" if yi > 0 else ("" if yi == 0 else "-")
    return f"{sign}{abs(yi):.1f}亿"


# =====================================================================
# Prompt 构造 + AI 调用
# =====================================================================


def _build_prompt(digest: dict[str, Any]) -> str:
    market_s = ", ".join(
        f"{m['name']} {_fmt_pct(m['change_pct_x10000'])}" for m in digest["market"]
    ) or "(无数据)"

    inflow_s = "; ".join(
        f"{i + 1}. {s['name']} {_fmt_yi(s['wan_x10000'])}"
        for i, s in enumerate(digest["top_inflow_sectors"])
    ) or "(无数据)"

    outflow_s = "; ".join(
        f"{i + 1}. {s['name']} {_fmt_yi(s['wan_x10000'])}"
        for i, s in enumerate(digest["top_outflow_sectors"])
    ) or "(无明显退潮)"

    dist = digest["holdings_signal_dist"]
    dist_s = " / ".join(f"{k} {v}" for k, v in dist.items()) or "(暂无持仓)"

    return (
        "你是 A 股主力资金分析助手。基于以下数据,用 1-2 句话(≤ 80 字)客观描述今日"
        "市场态势 + 我的持仓状态。R3 红线:绝不给出投资建议,绝不预测涨跌,只描述"
        "当前观察到的事实(主力净流入/流出、持仓信号分布)。\n\n"
        f"【市场】{market_s}\n"
        f"【Top 主力净流入】{inflow_s}\n"
        f"【Top 主力净流出】{outflow_s}\n"
        f"【我的持仓 {digest['holdings_total']} 只】{dist_s}\n"
    )


def _try_ai(digest: dict[str, Any]) -> str | None:
    """调 Anthropic;任何异常(含无 key)→ None,让调用方走 fallback。"""
    if not settings.anthropic_api_key:
        logger.info("dashboard ai-summary: ANTHROPIC_API_KEY not set, using fallback")
        return None
    try:
        import anthropic  # type: ignore

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=_AI_MODEL,
            max_tokens=_AI_MAX_TOKENS,
            messages=[{"role": "user", "content": _build_prompt(digest)}],
        )
        text = "".join(
            getattr(block, "text", "") for block in resp.content
        ).strip()
        return text or None
    except Exception as e:
        logger.warning(
            "dashboard ai-summary: AI call failed (%s: %s), using fallback",
            type(e).__name__, e,
        )
        return None


# =====================================================================
# Fallback:基于 digest 数据驱动,不输出空话
# =====================================================================


def _build_fallback_summary(digest: dict[str, Any]) -> str:
    """规则文案,客观描述。R3 兼容:不预测、不建议。"""
    parts: list[str] = []

    inflows = digest["top_inflow_sectors"][:3]
    if inflows:
        parts.append(
            "主力净流入 "
            + "、".join(f"{s['name']} {_fmt_yi(s['wan_x10000'])}" for s in inflows)
        )
    outflows = digest["top_outflow_sectors"][:3]
    if outflows:
        parts.append(
            "净流出 "
            + "、".join(f"{s['name']} {_fmt_yi(s['wan_x10000'])}" for s in outflows)
        )

    dist = digest["holdings_signal_dist"]
    total = digest["holdings_total"]
    if total > 0:
        dist_pieces = [f"{k} {v}" for k, v in dist.items() if v > 0]
        parts.append(f"持仓 {total} 只:{' / '.join(dist_pieces) or '全部 neutral'}")

    if not parts:
        return "今日尚无足够数据生成结论(等待 cron 15:20 完成数据采集)。"
    return "。".join(parts) + "。"


# =====================================================================
# 缓存读写 + 顶层 orchestration
# =====================================================================


def _read_cache_if_valid(latest_date: date | None, now: datetime) -> dict[str, Any] | None:
    """缓存命中条件:未过期 且 trade_date 跟最新一致。否则 None。"""
    if _cache is None:
        return None
    if _cache["expires_at"] <= now:
        return None
    if _cache["trade_date"] != latest_date:
        # 新一天的数据到了 → invalidate
        return None
    return _cache


def _write_cache(value: dict[str, Any], now: datetime) -> None:
    global _cache
    _cache = {
        **value,
        "expires_at": now + timedelta(seconds=_TTL_SECONDS),
    }


def get_or_build_summary(session: Session) -> dict[str, Any]:
    """顶层调用。返回 dict 含 trade_date / summary / generated_at / cached。

    空数据(库里完全没 sector_flow)→ 不缓存,每次都返回友好空态。
    """
    now = cn_now()
    latest_date = session.scalar(
        select(SectorFlowDaily.trade_date)
        .order_by(SectorFlowDaily.trade_date.desc())
        .limit(1)
    )

    # 缓存命中
    cached = _read_cache_if_valid(latest_date, now)
    if cached is not None:
        return {
            "trade_date": cached["trade_date"],
            "summary": cached["summary"],
            "generated_at": cached["generated_at"],
            "cached": True,
        }

    # 空数据:每次都返回不缓存
    if latest_date is None:
        return {
            "trade_date": None,
            "summary": "今日尚无数据,等待 cron 15:20 采集完成。",
            "generated_at": now,
            "cached": False,
        }

    # 构建 digest + AI / fallback
    digest = build_ai_input_digest(session, latest_date=latest_date)
    summary_text = _try_ai(digest) or _build_fallback_summary(digest)

    value = {
        "trade_date": latest_date,
        "summary": summary_text,
        "generated_at": now,
    }
    _write_cache(value, now)
    return {**value, "cached": False}
