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

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

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
    SectorBriefItem,
    SectorFlowResponse,
    SectorPersistenceItem,
    SectorPersistenceResponse,
    TopFundResponse,
    TopFundsResponse,
    TopSectorsResponse,
)
from src.services.dashboard_ai import build_extended_ai_summary
from src.services.dashboard_funds import build_top_funds
from src.services.dashboard_holdings import build_holdings_summary
from src.services.data_fetcher import DEFAULT_INDICES, fetch_market_index
from src.services.radar import build_intraday_radar
from src.services.sector_persistence import build_sector_persistence
from src.utils.date_helper import cn_now
from src.utils.money import int_to_nav, int_to_pct, int_to_wan_yuan

logger = logging.getLogger(__name__)

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


# =====================================================================
# PR19 — 市场温度扩展:在 DEFAULT_INDICES (4) 基础上加 4 个核心指数
# =====================================================================
# DEFAULT_INDICES 由 scheduler.daily_fetch 持续采集 → market_index_daily;
# 下面 4 个是新增,scheduler 没动,所以 DB 里没数据 → 走 sina 即时拉 + 5min
# 内存缓存,任一失败不影响其它指数。R 线:不改 data_fetcher / scheduler。
EXTRA_DASHBOARD_INDICES: list[tuple[str, str]] = [
    ("sh000688", "科创50"),
    ("sh000905", "中证500"),
    ("sh000852", "中证1000"),
    ("bj899050", "北证50"),
]

# 完整显示顺序(DB 4 + 即时 4)— 决定前端渲染先后
DASHBOARD_DISPLAY_INDICES: list[tuple[str, str]] = (
    list(DEFAULT_INDICES) + EXTRA_DASHBOARD_INDICES
)

# 即时拉的内存 TTL 缓存:5 min。首请求扛 4 个 sina HTTP,后续命中缓存。
_EXTRA_INDEX_CACHE_TTL = timedelta(minutes=5)
_extra_index_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}


def _clear_extra_index_cache_for_test() -> None:
    """供测试用,清空 extra 指数缓存。"""
    _extra_index_cache.clear()


def _fetch_extra_index_with_cache(
    code: str, name: str
) -> dict[str, Any] | None:
    """5 min TTL 缓存 + 即时 sina 拉。任何异常 → None,调用方跳过该指数。"""
    now = cn_now()
    cached = _extra_index_cache.get(code)
    if cached is not None:
        ts, data = cached
        if (now - ts) < _EXTRA_INDEX_CACHE_TTL:
            return data
    try:
        rows = fetch_market_index(code)
        if not rows:
            return None
        row = rows[0]
        data = {
            "index_code": code,
            "index_name": name,
            "trade_date": row["trade_date"],
            "close_x10000": row["close_x10000"],
            "change_pct_x10000": row["change_pct_x10000"],
            "turnover_wan_x10000": row.get("turnover_wan_x10000"),
        }
        _extra_index_cache[code] = (now, data)
        return data
    except Exception as e:
        logger.warning(
            "extra index %s/%s fetch failed: %s: %s",
            code, name, type(e).__name__, e,
        )
        return None


def _to_index_response_from_dict(d: dict[str, Any]) -> MarketIndexResponse:
    return MarketIndexResponse(
        index_code=d["index_code"],
        index_name=d["index_name"],
        trade_date=d["trade_date"],
        close=int_to_nav(d["close_x10000"]),
        change_pct=int_to_pct(d["change_pct_x10000"]),
        turnover_wan=(
            int_to_wan_yuan(d["turnover_wan_x10000"])
            if d.get("turnover_wan_x10000") is not None
            else None
        ),
    )


@router.get("/market", response_model=MarketSnapshotResponse)
def get_market_snapshot(db: Session = Depends(get_session)) -> MarketSnapshotResponse:
    """市场温度:返回最新交易日的核心 8 个指数(PR19 扩展)。

    - DEFAULT_INDICES 的 4 个 → 从 market_index_daily 读最新 trade_date
    - EXTRA_DASHBOARD_INDICES 的 4 个 → 即时 sina + 5min 内存缓存,
      失败不影响其它指数
    - 按 DASHBOARD_DISPLAY_INDICES 顺序输出
    - 顶层 trade_date 取所有出现指数中最大的(DB 和 extra 都可能贡献)
    - 全空 → {"trade_date": null, "indices": []} + HTTP 200
    """
    db_indices: list[MarketIndexResponse] = []
    latest_db_date = db.scalar(
        select(MarketIndexDaily.trade_date)
        .order_by(MarketIndexDaily.trade_date.desc())
        .limit(1)
    )
    if latest_db_date is not None:
        db_rows = list(db.scalars(
            select(MarketIndexDaily).where(
                MarketIndexDaily.trade_date == latest_db_date
            )
        ))
        db_indices = [_to_index_response(r) for r in db_rows]

    extra_indices: list[MarketIndexResponse] = []
    for code, name in EXTRA_DASHBOARD_INDICES:
        d = _fetch_extra_index_with_cache(code, name)
        if d is not None:
            extra_indices.append(_to_index_response_from_dict(d))

    all_indices = db_indices + extra_indices
    if not all_indices:
        return MarketSnapshotResponse(trade_date=None, indices=[])

    # 按 DASHBOARD_DISPLAY_INDICES 排;未知 code 排到末尾
    order_map = {code: i for i, (code, _) in enumerate(DASHBOARD_DISPLAY_INDICES)}
    unknown_offset = len(DASHBOARD_DISPLAY_INDICES)
    rows_sorted = sorted(
        all_indices,
        key=lambda r: (order_map.get(r.index_code, unknown_offset), r.index_code),
    )

    # 顶层 trade_date:用 DB 那批的(更可靠);全无 DB 时取 extra 最大
    trade_date_val = latest_db_date or max(r.trade_date for r in extra_indices)

    return MarketSnapshotResponse(
        trade_date=trade_date_val,
        indices=rows_sorted,
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


# =====================================================================
# 板块连续天数事实(PR20 — 基于 sector_flow_daily)
# =====================================================================


def _to_persistence_item(d: dict) -> SectorPersistenceItem:
    """service 出的 dict → Pydantic。main_inflow_yi 在这里算成亿元(已 /1e8)。"""
    wan_x10000 = d["main_inflow_wan_x10000"]
    yi = Decimal(wan_x10000) / Decimal(100_000_000)
    return SectorPersistenceItem(
        rank=d["rank"],
        sector_code=d["sector_code"],
        sector_name=d["sector_name"],
        sector_type=d["sector_type"],
        main_inflow_yi=yi,
        continuous_inflow_days=d["continuous_inflow_days"],
        continuous_outflow_days=d["continuous_outflow_days"],
        continuous_top20_days=d["continuous_top20_days"],
        # PR21 新增 5/10 日窗口
        last_5_inflow_days=d["last_5_inflow_days"],
        last_5_outflow_days=d["last_5_outflow_days"],
        last_5_top20_days=d["last_5_top20_days"],
        last_10_inflow_days=d["last_10_inflow_days"],
        last_10_outflow_days=d["last_10_outflow_days"],
        last_10_top20_days=d["last_10_top20_days"],
        # PR20 原 20 日窗口
        last_20_top20_days=d["last_20_top20_days"],
        last_20_inflow_days=d["last_20_inflow_days"],
        last_20_outflow_days=d["last_20_outflow_days"],
    )


@router.get(
    "/sectors/persistence", response_model=SectorPersistenceResponse
)
def get_sector_persistence(
    n: int = Query(20, ge=1, le=100, description="Top N(1..100,默认 20)"),
    sector_type: Literal["industry", "concept", "all"] = Query(
        "industry",
        description="过滤板块类型;all = 不过滤"
    ),
    db: Session = Depends(get_session),
) -> SectorPersistenceResponse:
    """板块连续天数事实(最新日 Top N + 历史连续天数)。

    R3 红线:全部字段都是**客观事实计数**,不是评分 / 健康分 / 投资建议。
    items 按最新日 main_inflow 降序排,不按连续天数 — 连续天数是附加事实。

    数据源固定 sector_flow_daily(收盘累计),**不读** intraday_sector_flow
    (盘中噪音不进入历史连续性判断)。

    空库 → {"trade_date": null, "sector_type": <param>, "items": []} + 200
    """
    raw = build_sector_persistence(db, n=n, sector_type=sector_type)
    return SectorPersistenceResponse(
        trade_date=raw["trade_date"],
        sector_type=raw["sector_type"],
        items=[_to_persistence_item(it) for it in raw["items"]],
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
# AI 结论(PR19 — 结构化,intraday 优先 + daily fallback,纯规则生成)
# =====================================================================


def _brief_to_response(d: dict[str, Any]) -> SectorBriefItem:
    return SectorBriefItem(
        sector_name=d["sector_name"],
        main_inflow_yi=d["main_inflow_yi"],
        change_pct=d["change_pct"],
    )


@router.get("/ai-summary", response_model=AISummaryResponse)
def get_ai_summary(db: Session = Depends(get_session)) -> AISummaryResponse:
    """AI 结论(Dashboard 首页 "AI 结论" 区数据源)。

    PR19 重构:
    - 优先用 intraday_sector_flow 最新 snapshot 生成结构化短摘要(source=intraday)
    - 若 intraday 库为空 → fallback 到 sector_flow_daily 最新交易日
      (source=daily_cached,但本路径**不调** Claude API,规则化生成)
    - cached 字段:仅在 source='daily_cached' 且命中旧 24h cache 时 true;
      PR19 新路径恒 false
    - 旧字段 trade_date/summary/generated_at/cached 保留作向后兼容
    """
    raw = build_extended_ai_summary(db)
    return AISummaryResponse(
        source=raw["source"],
        summary_text=raw["summary_text"],
        inflow_top3=[_brief_to_response(d) for d in raw["inflow_top3"]],
        outflow_top3=[_brief_to_response(d) for d in raw["outflow_top3"]],
        holding_stats=raw["holding_stats"],
        data_date=raw["data_date"],
        data_time=raw["data_time"],
        cached=raw["cached"],
        # 旧字段
        trade_date=raw["trade_date"],
        summary=raw["summary"],
        generated_at=raw["generated_at"],
    )
