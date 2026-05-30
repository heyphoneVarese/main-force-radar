"""Dashboard 只读聚合路由(Phase 5.1)。

R 红线兼容:
- 只读 — 不写任何表,不动 scheduler/notifier/data_fetcher
- 整数 money 走 utils/money 的反算函数,绝不让 float 染指
- /api 已被 nginx 反代 → /api/dashboard/* 暴露给前端 dashboard 页

后续 PR 还会在本路由下加:
- GET /api/dashboard/sectors/top
- GET /api/dashboard/funds/top
- GET /api/dashboard/holdings-summary
- GET /api/dashboard/ai-summary
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import get_session
from src.models import MarketIndexDaily, SectorFlowDaily
from src.schemas.dashboard import (
    HoldingSignalResponse,
    HoldingsSummaryResponse,
    MarketIndexResponse,
    MarketSnapshotResponse,
    MatchedSector,
    SectorFlowResponse,
    TopFundResponse,
    TopFundsResponse,
    TopSectorsResponse,
)
from src.services.dashboard_funds import build_top_funds
from src.services.dashboard_holdings import build_holdings_summary
from src.services.data_fetcher import DEFAULT_INDICES
from src.utils.money import int_to_nav, int_to_pct, int_to_wan_yuan

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _to_index_response(row: MarketIndexDaily) -> MarketIndexResponse:
    """ORM 行 → Pydantic 响应。整数字段全部走 money 反算。"""
    return MarketIndexResponse(
        index_code=row.index_code,
        index_name=row.index_name,
        trade_date=row.trade_date,
        close=int_to_nav(row.close_x10000),
        change_pct=int_to_pct(row.change_pct_x10000),
        turnover_wan=(
            int_to_wan_yuan(row.turnover_wan_x10000)
            if row.turnover_wan_x10000 is not None
            else None
        ),
    )


@router.get("/market", response_model=MarketSnapshotResponse)
def get_market_snapshot(db: Session = Depends(get_session)) -> MarketSnapshotResponse:
    """市场温度:返回最新交易日的 4 大指数。

    - 取整张 market_index_daily 里最大的 trade_date
    - 该日的所有指数,按 DEFAULT_INDICES 顺序排列(上证/深成/创业板/沪深300)
    - 不在 DEFAULT_INDICES 里的指数(理论上不会有)排到末尾
    - 空库 → {"trade_date": null, "indices": []} + HTTP 200
    """
    latest_date = db.scalar(select(MarketIndexDaily.trade_date)
                            .order_by(MarketIndexDaily.trade_date.desc())
                            .limit(1))
    if latest_date is None:
        return MarketSnapshotResponse(trade_date=None, indices=[])

    rows = db.scalars(
        select(MarketIndexDaily).where(MarketIndexDaily.trade_date == latest_date)
    ).all()

    # 按 DEFAULT_INDICES 顺序排;未知 index_code 排到末尾(按 code 字母序兜底)
    order_map = {code: i for i, (code, _) in enumerate(DEFAULT_INDICES)}
    unknown_offset = len(DEFAULT_INDICES)
    rows_sorted = sorted(
        rows,
        key=lambda r: (order_map.get(r.index_code, unknown_offset), r.index_code),
    )

    return MarketSnapshotResponse(
        trade_date=latest_date,
        indices=[_to_index_response(r) for r in rows_sorted],
    )


# =====================================================================
# Top 板块(按主力净流入降序)
# =====================================================================


def _to_sector_response(row: SectorFlowDaily, rank: int) -> SectorFlowResponse:
    """ORM 行 → Pydantic。R1 整数全走 money 反算;nullable pct 字段保留 None。"""
    return SectorFlowResponse(
        rank=rank,
        sector_code=row.sector_code,
        sector_name=row.sector_name,
        sector_type=row.sector_type,
        main_inflow_wan=int_to_wan_yuan(row.main_inflow_wan_x10000),
        main_inflow_pct=(
            int_to_pct(row.main_inflow_pct_x10000)
            if row.main_inflow_pct_x10000 is not None
            else None
        ),
        change_pct=(
            int_to_pct(row.change_pct_x10000)
            if row.change_pct_x10000 is not None
            else None
        ),
    )


@router.get("/sectors/top", response_model=TopSectorsResponse)
def get_top_sectors(
    n: int = Query(20, ge=1, le=100, description="返回 Top N(1..100,默认 20)"),
    sector_type: Literal["industry", "concept", "all"] = Query(
        "industry",
        description="过滤板块类型;all = 不过滤,行业/概念混排"
    ),
    db: Session = Depends(get_session),
) -> TopSectorsResponse:
    """Top N 板块(最新交易日,按主力净流入降序)。

    - 取整张 sector_flow_daily 最大的 trade_date(可能跟 market_index_daily 不同步)
    - 该日所有板块按 main_inflow_wan_x10000 DESC 排
    - 负流入会沉底,Top N 就是"强势板块"
    - 空库 → {"trade_date": null, "sector_type": <param>, "sectors": []} + HTTP 200
    """
    latest_date = db.scalar(
        select(SectorFlowDaily.trade_date)
        .order_by(SectorFlowDaily.trade_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return TopSectorsResponse(
            trade_date=None, sector_type=sector_type, sectors=[]
        )

    stmt = select(SectorFlowDaily).where(SectorFlowDaily.trade_date == latest_date)
    if sector_type != "all":
        stmt = stmt.where(SectorFlowDaily.sector_type == sector_type)
    stmt = stmt.order_by(SectorFlowDaily.main_inflow_wan_x10000.desc()).limit(n)

    rows = db.scalars(stmt).all()
    return TopSectorsResponse(
        trade_date=latest_date,
        sector_type=sector_type,
        sectors=[_to_sector_response(r, i + 1) for i, r in enumerate(rows)],
    )


# =====================================================================
# 持仓摘要(包装 SignalEngine.get_fund_signal_summary)
# =====================================================================


@router.get("/holdings-summary", response_model=HoldingsSummaryResponse)
def get_holdings_summary(
    db: Session = Depends(get_session),
) -> HoldingsSummaryResponse:
    """每只持仓基金的信号摘要(Dashboard "我的持仓分析" 区数据源)。

    走 services/dashboard_holdings.build_holdings_summary,本路由层只负责
    R1 整数 → Decimal 反算 + Pydantic 校验。

    - 空持仓 → 200 + {"trade_date": null, "holdings": []}
    - not_applicable 基金(QDII / 指数 / 债基,sector_aliases 显式无 BK 对应)
      → 各数值字段 null,reason 解释原因
    - via_sector 有但当日 sector_flow_daily 没数据 → main_inflow_wan 仍有
      (来自 Signal 表自带),change_pct = null
    """
    raw = build_holdings_summary(db)
    holdings_response = [
        HoldingSignalResponse(
            fund_code=h["fund_code"],
            fund_name=h["fund_name"],
            related_sectors=h["related_sectors"],
            signal_type=h["signal_type"],
            persistence_score=h["persistence_score"],
            via_sector=h["via_sector"],
            main_inflow_wan=(
                int_to_wan_yuan(h["main_inflow_wan_x10000"])
                if h["main_inflow_wan_x10000"] is not None
                else None
            ),
            change_pct=(
                int_to_pct(h["change_pct_x10000"])
                if h["change_pct_x10000"] is not None
                else None
            ),
            reason=h["reason"],
        )
        for h in raw["holdings"]
    ]
    return HoldingsSummaryResponse(
        trade_date=raw["trade_date"],
        holdings=holdings_response,
    )


# =====================================================================
# Top N 基金(按映射板块流强度)
# =====================================================================


@router.get("/funds/top", response_model=TopFundsResponse)
def get_top_funds(
    n: int = Query(20, ge=1, le=100, description="返回 Top N(1..100,默认 20)"),
    db: Session = Depends(get_session),
) -> TopFundsResponse:
    """Top N 基金(最新交易日,按映射板块主力净流入降序)。

    走 services/dashboard_funds.build_top_funds。本路由层只做 R1 整数 → Decimal
    反算 + Pydantic 校验。

    过滤策略(无数据不上榜):
    - funds.related_sectors 为空 → 跳过
    - 全部 mapped 标签 → 无 BK code → 跳过
    - mapped BK 都没有当日 sector_flow_daily 数据 → 跳过

    因此 funds 长度 ≤ n;空库 / 全无数据 → 200 + {trade_date: null, funds: []}。
    """
    raw = build_top_funds(db, n=n)
    funds_response = [
        TopFundResponse(
            rank=f["rank"],
            fund_code=f["fund_code"],
            fund_name=f["fund_name"],
            related_sectors=f["related_sectors"],
            matched_sectors=[
                MatchedSector(
                    sector_code=m["sector_code"], sector_name=m["sector_name"]
                )
                for m in f["matched_sectors"]
            ],
            score=f["score"],
            main_inflow_wan=int_to_wan_yuan(f["main_inflow_wan_x10000"]),
            change_pct=(
                int_to_pct(f["change_pct_x10000"])
                if f["change_pct_x10000"] is not None
                else None
            ),
            reason=f["reason"],
        )
        for f in raw["funds"]
    ]
    return TopFundsResponse(trade_date=raw["trade_date"], funds=funds_response)
