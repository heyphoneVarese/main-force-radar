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

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import get_session
from src.models import IntradaySectorFlow, MarketIndexDaily, SectorFlowDaily
from src.schemas.dashboard import (
    AISummaryResponse,
    DashboardRadarResponse,
    HoldingSignalResponse,
    HoldingsSummaryResponse,
    IntradayTopSectorsResponse,
    MarketIndexResponse,
    MarketSnapshotResponse,
    MatchedSector,
    RadarFundItem,
    SectorFlowResponse,
    TopFundResponse,
    TopFundsResponse,
    TopSectorsResponse,
)
from src.services.dashboard_ai import get_or_build_summary
from src.services.dashboard_funds import build_top_funds
from src.services.dashboard_holdings import build_holdings_summary
from src.services.data_fetcher import DEFAULT_INDICES
from src.services.radar import build_intraday_radar
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
# 盘中实时 Top 板块(PR15 — 新表 intraday_sector_flow)
# =====================================================================


def _to_intraday_sector_response(
    row: IntradaySectorFlow, rank: int
) -> SectorFlowResponse:
    """ORM 行 → Pydantic。复用 SectorFlowResponse 形态(rank + 数值字段)。"""
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


@router.get("/intraday/sectors/top", response_model=IntradayTopSectorsResponse)
def get_intraday_top_sectors(
    n: int = Query(20, ge=1, le=100, description="Top N(1..100,默认 20)"),
    sector_type: Literal["industry", "concept", "all"] = Query(
        "industry",
        description="过滤板块类型;all = 不过滤,行业/概念混排"
    ),
    db: Session = Depends(get_session),
) -> IntradayTopSectorsResponse:
    """盘中实时 Top N 板块(最新 snapshot,按主力净流入降序)。

    - 取 intraday_sector_flow 最大的 snapshot_time(精确到分钟)
    - 同一 snapshot 内所有板块按 main_inflow_wan_x10000 DESC 排
    - 空库(集合竞价前 / 周末 / 还没采过)→ trade_date=null,
      snapshot_time=null, sectors=[],HTTP 200

    跟 /sectors/top(daily)是平行端点 — 此端点 100% 不影响 daily 行为。
    """
    latest_snapshot = db.scalar(
        select(IntradaySectorFlow.snapshot_time)
        .order_by(IntradaySectorFlow.snapshot_time.desc())
        .limit(1)
    )
    if latest_snapshot is None:
        return IntradayTopSectorsResponse(
            trade_date=None,
            snapshot_time=None,
            sector_type=sector_type,
            sectors=[],
        )

    stmt = select(IntradaySectorFlow).where(
        IntradaySectorFlow.snapshot_time == latest_snapshot
    )
    if sector_type != "all":
        stmt = stmt.where(IntradaySectorFlow.sector_type == sector_type)
    stmt = stmt.order_by(
        IntradaySectorFlow.main_inflow_wan_x10000.desc()
    ).limit(n)

    rows = db.scalars(stmt).all()
    # trade_date 取 snapshot_time 的日期部分(snapshot 自带,但更省一次查询)
    trade_date_val = (
        rows[0].trade_date if rows else latest_snapshot.date()
    )

    return IntradayTopSectorsResponse(
        trade_date=trade_date_val,
        snapshot_time=latest_snapshot,
        sector_type=sector_type,
        sectors=[
            _to_intraday_sector_response(r, i + 1)
            for i, r in enumerate(rows)
        ],
    )


# =====================================================================
# 主力雷达(PR16)— intraday_sector_flow → funds 映射
# =====================================================================


def _to_radar_item(raw: dict) -> RadarFundItem:
    """service 出的 dict(_x10000 整数)→ Pydantic Decimal。
    sector_change_pct 用百分数(2.10 表 2.10%),跟雷达 spec 一致 —
    这是跟 sectors/top 的 fraction 形式刻意不同的"展示口径"。"""
    wan_x10000 = raw["sector_main_inflow_wan_x10000"]
    wan = int_to_wan_yuan(wan_x10000)         # 万元
    yi = wan / Decimal(10_000)                # 亿元 = 万元 / 10000
    cp_x10000 = raw["sector_change_pct_x10000"]
    return RadarFundItem(
        fund_code=raw["fund_code"],
        fund_name=raw["fund_name"],
        matched_sector=raw["matched_sector"],
        sector_code=raw["sector_code"],
        sector_rank=raw["sector_rank"],
        sector_main_inflow_wan=wan,
        sector_main_inflow_yi=yi,
        sector_change_pct=(
            Decimal(cp_x10000) / Decimal(100)
            if cp_x10000 is not None else None
        ),
        score=raw["score"],
        purity_score=raw["purity_score"],
        badge=raw["badge"],
    )


@router.get("/radar", response_model=DashboardRadarResponse)
def get_dashboard_radar(
    mode: Literal["intraday"] = Query(
        "intraday", description="V1 只支持 'intraday'"
    ),
    n: int = Query(20, ge=1, le=100, description="每组(holdings/candidates)最多返回 N 条"),
    db: Session = Depends(get_session),
) -> DashboardRadarResponse:
    """主力雷达 — 把盘中实时强势板块映射到 holdings + candidates。

    走 services/radar.build_intraday_radar。R3 红线:输出只有"客观雷达分",
    不带任何买卖建议。

    - mode='intraday' → 用 intraday_sector_flow 最新 snapshot
    - sector_type 固定 industry(第一版,避免 concept 噪声)
    - holdings/candidates 各按 (score DESC, sector_rank ASC) 排,各取 n
    - 空库 → mode='intraday', trade_date=null, snapshot_time=null, [], []
    """
    raw = build_intraday_radar(db, n=n)
    return DashboardRadarResponse(
        mode=raw["mode"],
        trade_date=raw["trade_date"],
        snapshot_time=raw["snapshot_time"],
        holdings=[_to_radar_item(h) for h in raw["holdings"]],
        candidates=[_to_radar_item(c) for c in raw["candidates"]],
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


# =====================================================================
# AI 一句话结论(24h TTL 缓存)
# =====================================================================


@router.get("/ai-summary", response_model=AISummaryResponse)
def get_ai_summary(db: Session = Depends(get_session)) -> AISummaryResponse:
    """AI 一句话结论(Dashboard 首页"AI 结论"区数据源)。

    走 services/dashboard_ai.get_or_build_summary,该服务负责:
    - 24h 模块级 TTL 缓存
    - trade_date 变化时自动 invalidate(15:20 cron 新数据到 → 下次调用重算)
    - ANTHROPIC_API_KEY 缺失或 Anthropic 调用失败 → graceful fallback
      (不报错;HTTP 仍 200;fallback 基于真实 digest 渲染,非空话)

    返回:
    - trade_date: 最新有 sector_flow 数据的日期;空库 → null
    - summary  : 一句话结论
    - generated_at: 该 summary 生成时刻
    - cached   : true=命中缓存 / false=本次新生成
    """
    raw = get_or_build_summary(db)
    return AISummaryResponse(**raw)
