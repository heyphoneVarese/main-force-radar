"""Dashboard Top N 基金聚合(Phase 5.1 PR4)。

排序键:基金所有 mapped 板块(via sector_aliases 翻译 funds.related_sectors
中文标签)中,主力净流入最大的那个值。

为什么用 max 而不是 sum:
- "最强基金"语义直观 — 一只基金通过它最强的那个板块取得排名
- sum 会让多板块基金占便宜(同一资金量被多次累加),失真
- max 跟 PR3 holdings-summary 的 via_sector 选择一致(SignalEngine 也是取最强)

score:SignalEngine.calculate_persistence_score(via_sector).total — 0-9,
跟 PR3 同公式(R6:同一指标只有一个口径)。

【过滤策略】不返回以下基金:
- funds.related_sectors 为空(QDII / 指数 / 债基)
- 全部 mapped 标签 → 无 BK code(sector_aliases 显式无对应)
- mapped BK 都没有当日 sector_flow_daily 数据
理由:"最强 N 基金"是排行榜,无数据不上榜;占位用 null 会让前端逻辑变重。

R 线兼容:只读 funds / sector_aliases / sector_flow_daily / signals(给
SignalEngine 跑分用,signals 本身不写)。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, SectorFlowDaily
from src.services.sector_mapping import get_sectors_for_fund
from src.services.signal_engine import SignalEngine


def build_top_funds(
    session: Session, n: int = 20, as_of: date | None = None
) -> dict[str, Any]:
    """聚合 Top N 基金。

    返回结构(_x10000 整数原样,API 层负责转 Decimal):

        {
          "trade_date": date | None,
          "funds": [
            {
              "rank": 1,                                    # 1-based,排序后填
              "fund_code": str,
              "fund_name": str,
              "related_sectors": list[str],                 # funds.related_sectors 原样
              "matched_sectors": [                          # 当日有 sector_flow 数据的 mapped BK
                {"sector_code": "BK0727", "sector_name": "半导体"}, ...
              ],
              "via_sector_code": str,                       # 决定排名的那个 BK
              "via_sector_name": str,
              "score": int,                                 # SignalEngine 持续性 0-9
              "main_inflow_wan_x10000": int,
              "change_pct_x10000": int | None,
              "reason": str,                                # 人类可读的"为什么排这"
            },
            ...
          ]
        }

    无任何 sector_flow 数据 → {"trade_date": None, "funds": []}
    """
    # 1. 取最新的 sector_flow trade_date
    latest_date = session.scalar(
        select(SectorFlowDaily.trade_date)
        .order_by(SectorFlowDaily.trade_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return {"trade_date": None, "funds": []}

    # 2. 一次性把当日所有 sector_flow 拉成 dict,避免后面 N×M 查询
    flows_by_code: dict[str, SectorFlowDaily] = {
        row.sector_code: row
        for row in session.scalars(
            select(SectorFlowDaily).where(SectorFlowDaily.trade_date == latest_date)
        )
    }
    if not flows_by_code:
        return {"trade_date": None, "funds": []}

    # 3. 遍历所有 funds,算每只基金的 via_sector + score
    engine = SignalEngine(session)
    candidates: list[dict[str, Any]] = []

    for fund in session.scalars(select(Fund)):
        bk_codes = get_sectors_for_fund(session, fund.fund_code)
        matched_flows = [
            (code, flows_by_code[code]) for code in bk_codes if code in flows_by_code
        ]
        if not matched_flows:
            # 过滤策略:无映射 / 无当日数据 → 不上榜
            continue

        # via_sector = 净流入最大的那个(可能是负数 = 最不差)
        via_code, via_flow = max(
            matched_flows, key=lambda p: p[1].main_inflow_wan_x10000
        )
        sb = engine.calculate_persistence_score(via_code, as_of=latest_date)

        flow_yi = via_flow.main_inflow_wan_x10000 / 10_000 / 10_000
        direction = (
            "净流入" if flow_yi > 0 else ("净流出" if flow_yi < 0 else "持平")
        )
        reason = (
            f"via {via_flow.sector_name} ({via_code}): "
            f"持续性 {sb.total}/9; 主力{direction} {abs(flow_yi):.1f} 亿"
        )

        candidates.append({
            "fund_code": fund.fund_code,
            "fund_name": fund.fund_name,
            "related_sectors": list(fund.related_sectors or []),
            "matched_sectors": [
                {"sector_code": code, "sector_name": flow.sector_name}
                for code, flow in matched_flows
            ],
            "via_sector_code": via_code,
            "via_sector_name": via_flow.sector_name,
            "score": sb.total,
            "main_inflow_wan_x10000": via_flow.main_inflow_wan_x10000,
            "change_pct_x10000": via_flow.change_pct_x10000,
            "reason": reason,
        })

    # 4. 按 via_sector 流入降序排,正流入在前,负流入沉底
    candidates.sort(key=lambda c: c["main_inflow_wan_x10000"], reverse=True)
    top = candidates[:n]
    for i, c in enumerate(top, start=1):
        c["rank"] = i

    return {"trade_date": latest_date, "funds": top}
