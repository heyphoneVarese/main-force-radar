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

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import get_session
from src.models import MarketIndexDaily
from src.schemas.dashboard import MarketIndexResponse, MarketSnapshotResponse
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
