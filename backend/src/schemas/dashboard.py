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


class HoldingSignalResponse(BaseModel):
    """单只持仓基金的信号摘要。

    `signal_type` 取值见 src.models.enums.SignalType:
    bullish / bearish / warning / neutral / not_applicable。
    R3.1 红线:绝不出现 buy/sell/long/short/hold。
    """

    fund_code: str
    fund_name: str | None = Field(description="未在 funds 表登记则 null")
    related_sectors: list[str] = Field(
        description="funds.related_sectors 的中文标签数组,如 ['半导体','AI']"
    )
    signal_type: str = Field(
        description="bullish / bearish / warning / neutral / not_applicable"
    )
    persistence_score: int = Field(
        ge=0,
        description="持续性 0-9;not_applicable / 无 sector_flow 数据时为 0"
    )
    via_sector: str | None = Field(
        default=None,
        description="决定性板块的 eastmoney code(如 BK0727);不适用 / 无数据时 null"
    )
    main_inflow_wan: Decimal | None = Field(
        default=None,
        description="via_sector 最新 Signal 的主力净流入(万元;负=净流出);"
                    "无 via_sector 时 null"
    )
    change_pct: Decimal | None = Field(
        default=None,
        description="via_sector 同日 sector_flow_daily 涨跌幅(小数 0.0312=3.12%);"
                    "无对应行情时 null"
    )
    reason: str = Field(description="SignalEngine 给出的人类可读说明")


class HoldingsSummaryResponse(BaseModel):
    """所有持仓基金的信号摘要聚合。

    trade_date:所有 holdings 的 via_sector Signal 中最大的那个;
    若所有持仓都 not_applicable / 无 Signal,则为 null。
    """

    trade_date: date | None = Field(
        description="所有持仓的最新 signal trade_date;前端显示'截至 X 日'"
    )
    holdings: list[HoldingSignalResponse] = Field(
        description="按 fund_code 字典序排;无持仓 → []"
    )


class MatchedSector(BaseModel):
    """基金当日实际匹配到的 BK 板块(在 sector_flow_daily 有数据)。"""

    sector_code: str = Field(description="如 BK0727")
    sector_name: str


class TopFundResponse(BaseModel):
    """Top N 基金排行的单条记录。

    排序键:via_sector 的当日 main_inflow_wan(降序)。
    score:SignalEngine 持续性 0-9,跟 PR3 holdings-summary 同公式。
    """

    rank: int = Field(ge=1, description="名次(1-based)")
    fund_code: str
    fund_name: str
    related_sectors: list[str] = Field(
        description="funds.related_sectors 原始中文标签数组"
    )
    matched_sectors: list[MatchedSector] = Field(
        description="当日有 sector_flow 数据的 mapped BK 板块;可能 1..N 条"
    )
    score: int = Field(
        ge=0, le=9,
        description="via_sector 的 SignalEngine 持续性总分(基础 0-4 + 连续 0-3 + 量价 0-2)"
    )
    main_inflow_wan: Decimal = Field(
        description="via_sector(matched 中流入最强的)当日主力净流入,万元;"
                    "可为负(=该 fund 所有 mapped 板块都在退潮,取最不差的)"
    )
    change_pct: Decimal | None = Field(
        default=None,
        description="via_sector 当日涨跌幅(小数);sector_flow 当字段为 null 时也为 null"
    )
    reason: str = Field(description="人类可读的排名解释")


class TopFundsResponse(BaseModel):
    """Top N 基金排行。

    过滤策略:无 related_sectors / 无 mapped BK / mapped BK 无当日数据 → 不上榜。
    因此 funds 长度 ≤ n,可能更少。空库或全无数据 → {trade_date: null, funds: []}。
    """

    trade_date: date | None = Field(
        description="最新有 sector_flow 数据的交易日;空 → null"
    )
    funds: list[TopFundResponse] = Field(
        description="按 via_sector main_inflow 降序排;最多 n 条"
    )
