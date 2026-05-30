"""Dashboard API 的 Pydantic schema。

对外暴露 Decimal(用户面友好),内部走 money.py 转 int(R1)。
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class MarketIndexResponse(BaseModel):
    """单个市场指数(market_index_daily 一行)。

    所有数值字段都用 Decimal 字符串透传给前端,语义与 utils/money.py 的
    int_to_nav / int_to_pct / int_to_wan_yuan 反算一致。
    """

    index_code: str = Field(description="如 sh000001 / sz399001 / sz399006 / sh000300")
    index_name: str = Field(description="如 上证指数 / 深证成指 / 创业板指 / 沪深300")
    trade_date: date
    close: Decimal = Field(description="收盘点位,如 3120.5000")
    change_pct: Decimal = Field(
        description="涨跌幅(小数,0.0066 = 0.66%);前端乘 100 显示百分比"
    )
    turnover_wan: Decimal | None = Field(
        default=None,
        description="成交额,万元;sina 数据源无 amount 时为 null"
    )


class MarketSnapshotResponse(BaseModel):
    """最新一天的 4 个市场指数(顺序固定:上证/深成/创业板/沪深300)。

    trade_date 顶层冗余一份,前端不用从 indices[0] 里挖。空库时 indices=[],
    trade_date=null,HTTP 仍是 200(让前端空态友好提示)。
    """

    trade_date: date | None = Field(
        description="最新有数据的交易日。空库 → null"
    )
    indices: list[MarketIndexResponse] = Field(
        description="按 data_fetcher.DEFAULT_INDICES 顺序排列;最多 4 条"
    )


class SectorFlowResponse(BaseModel):
    """单个板块的资金流(sector_flow_daily 一行)。

    所有数值字段用 Decimal,语义与 int_to_wan_yuan / int_to_pct 反算一致。
    """

    rank: int = Field(ge=1, description="按 main_inflow_wan 降序的名次(1-based)")
    sector_code: str = Field(description="如 BK0428(电池);concept/region 同表")
    sector_name: str
    sector_type: str = Field(description="industry / concept / region")
    main_inflow_wan: Decimal = Field(
        description="主力净流入,万元;负值=净流出"
    )
    main_inflow_pct: Decimal | None = Field(
        default=None,
        description="主力净流入占比(小数,0.083 = 8.3%);akshare 偶尔为 null"
    )
    change_pct: Decimal | None = Field(
        default=None,
        description="今日涨跌幅(小数,0.0234 = 2.34%);akshare 偶尔为 null"
    )


class TopSectorsResponse(BaseModel):
    """最新交易日 Top N 板块。

    平行 MarketSnapshotResponse:trade_date 顶层冗余,空库时为 null。
    sector_type 回显请求参数(industry / concept / all),前端可据此渲染 tab。
    """

    trade_date: date | None = Field(description="最新有数据的交易日;空库 → null")
    sector_type: str = Field(description="请求的过滤类型:industry / concept / all")
    sectors: list[SectorFlowResponse] = Field(
        description="按 main_inflow_wan 降序排;最多 n 条(默认 20)"
    )
