"""Dashboard 持仓摘要聚合(Phase 5.1 PR3)。

把 SignalEngine.get_fund_signal_summary 这个单基金函数批量化,并补两个
Dashboard UI 用到、但底层 summary 没暴露的字段:
- main_inflow_wan_x10000:via_sector 最新 Signal 的主力净流入
- change_pct_x10000   :via_sector 对应 trade_date 的 sector_flow_daily 涨跌幅

Read-only。R 线兼容(不改 DB / scheduler / notifier / data_fetcher / models)。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, Holding, SectorFlowDaily, Signal
from src.services.signal_engine import SignalEngine


def build_holdings_summary(
    session: Session, as_of: date | None = None
) -> dict[str, Any]:
    """聚合所有持仓的信号摘要。

    返回结构(_x10000 整数原样,API 层负责转 Decimal):

        {
          "trade_date": date | None,         # 所有 holdings 中最大的 signal trade_date
          "holdings": [
            {
              "fund_code": str,
              "fund_name": str | None,
              "related_sectors": list[str],          # funds.related_sectors 中文标签
              "signal_type": str,                    # bullish/bearish/warning/neutral/not_applicable
              "persistence_score": int,              # 0-9;not_applicable / no_data 时为 0
              "via_sector": str | None,              # 决定性板块 code(BK0727);否则 None
              "main_inflow_wan_x10000": int | None,  # via_sector 最新 Signal 流入
              "change_pct_x10000": int | None,       # via_sector 同日 sector_flow 涨跌幅
              "reason": str,                         # SignalEngine 给的人类可读说明
            },
            ...
          ]
        }

    设计要点:
    - holdings 按 fund_code 排序,前端渲染稳定
    - 没持仓 → {"trade_date": None, "holdings": []}
    - not_applicable 基金(QDII / 指数 / 债基)— 字段全填 None,reason 解释原因
    - 有 via_sector 但 sector_flow_daily 该日没数据 → main_inflow_wan 仍来自 Signal,
      change_pct=None(Signal 表自带 main_inflow,SectorFlowDaily 表才有 change_pct)
    - 顶层 trade_date 用于前端显示"截至 X 日";所有持仓都 not_applicable 时为 None
    """
    engine = SignalEngine(session)
    holdings = session.scalars(select(Holding).order_by(Holding.fund_code)).all()

    out_holdings: list[dict[str, Any]] = []
    latest_trade_date: date | None = None

    for h in holdings:
        summary = engine.get_fund_signal_summary(h.fund_code, as_of=as_of)
        fund = session.get(Fund, h.fund_code)
        related = list(fund.related_sectors) if fund and fund.related_sectors else []

        via_sector: str | None = summary.get("via_sector")
        main_inflow_wan_x10000: int | None = None
        change_pct_x10000: int | None = None

        if via_sector:
            # 同 SignalEngine.get_fund_signal_summary 内部逻辑:取该 sector 最新一条
            sig = session.scalar(
                select(Signal)
                .where(Signal.target_type == "sector")
                .where(Signal.target_code == via_sector)
                .order_by(Signal.trade_date.desc())
                .limit(1)
            )
            if sig is not None:
                main_inflow_wan_x10000 = sig.main_inflow_wan_x10000
                if latest_trade_date is None or sig.trade_date > latest_trade_date:
                    latest_trade_date = sig.trade_date
                # change_pct 从 sector_flow_daily 同 (code, date) 拿;可能没有
                flow = session.scalar(
                    select(SectorFlowDaily)
                    .where(SectorFlowDaily.sector_code == via_sector)
                    .where(SectorFlowDaily.trade_date == sig.trade_date)
                    .limit(1)
                )
                if flow is not None:
                    change_pct_x10000 = flow.change_pct_x10000

        out_holdings.append({
            "fund_code": h.fund_code,
            "fund_name": summary.get("fund_name"),
            "related_sectors": related,
            "signal_type": summary["signal_type"],
            "persistence_score": int(summary.get("score") or 0),
            "via_sector": via_sector,
            "main_inflow_wan_x10000": main_inflow_wan_x10000,
            "change_pct_x10000": change_pct_x10000,
            "reason": summary.get("reason") or "",
        })

    return {"trade_date": latest_trade_date, "holdings": out_holdings}
