"""Dashboard API 的 Pydantic schema。

对外暴露 Decimal(用户面友好),内部走 money.py 转 int(R1)。
"""

from datetime import date, datetime
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


class IntradayTopSectorsResponse(BaseModel):
    """盘中实时 Top N 板块快照(PR15)。

    跟 TopSectorsResponse 区别:多一个 `snapshot_time`(精确到分钟)。
    `sectors` 复用 SectorFlowResponse 形态,数值字段语义一致(int_to_*)。

    空库 → trade_date=null, snapshot_time=null, sectors=[]。
    """

    trade_date: date | None = Field(
        description="最新有 snapshot 的交易日(snapshot_time 的日期部分);空 → null"
    )
    snapshot_time: datetime | None = Field(
        description="最新 snapshot 时刻(Asia/Shanghai 精确到分钟);空 → null"
    )
    sector_type: str = Field(description="请求的过滤类型:industry / concept / all")
    sectors: list[SectorFlowResponse] = Field(
        description="按 main_inflow_wan 降序排;最多 n 条(默认 20)"
    )


class SectorPersistenceItem(BaseModel):
    """板块连续天数事实(PR20)。

    R3 红线:**全部是客观事实计数**,不是 score / health 评分 / 投资建议。
    字段命名一律 _days / _count,提醒消费方不要再合成派生分。
    """

    rank: int = Field(ge=1, description="最新日按 main_inflow 降序的排名(1-based)")
    sector_code: str
    sector_name: str
    sector_type: str = Field(description="industry / concept / region")
    main_inflow_yi: Decimal = Field(description="最新日主力净流入,亿元")

    continuous_inflow_days: int = Field(
        ge=0,
        description="从最新日起连续 main_inflow > 0 的天数;遇 <=0 或缺记录则停"
    )
    continuous_outflow_days: int = Field(
        ge=0,
        description="从最新日起连续 main_inflow < 0 的天数;遇 >=0 或缺记录则停"
    )
    continuous_top20_days: int = Field(
        ge=0,
        description="从最新日起连续在同 sector_type Top20 里的天数;遇缺席则停"
    )

    # ===== PR21 新增:5/10 日窗口 =====
    last_5_inflow_days: int = Field(
        ge=0, le=5,
        description="最近 5 个交易日内 main_inflow > 0 的天数"
    )
    last_10_inflow_days: int = Field(
        ge=0, le=10,
        description="最近 10 个交易日内 main_inflow > 0 的天数"
    )
    last_5_outflow_days: int = Field(
        ge=0, le=5,
        description="最近 5 个交易日内 main_inflow < 0 的天数"
    )
    last_10_outflow_days: int = Field(
        ge=0, le=10,
        description="最近 10 个交易日内 main_inflow < 0 的天数"
    )
    last_5_top20_days: int = Field(
        ge=0, le=5,
        description="最近 5 个交易日内进入 Top20 的次数"
    )
    last_10_top20_days: int = Field(
        ge=0, le=10,
        description="最近 10 个交易日内进入 Top20 的次数"
    )

    # ===== PR20 原 20 日窗口(保留向后兼容)=====
    last_20_top20_days: int = Field(
        ge=0, le=20,
        description="最近 20 个交易日内进入 Top20 的次数"
    )
    last_20_inflow_days: int = Field(
        ge=0, le=20,
        description="最近 20 个交易日内 main_inflow > 0 的天数"
    )
    last_20_outflow_days: int = Field(
        ge=0, le=20,
        description="最近 20 个交易日内 main_inflow < 0 的天数"
    )


class SectorPersistenceResponse(BaseModel):
    """板块连续天数响应(PR20)。

    空库 → trade_date=null, items=[]。items 按最新日 main_inflow 降序,
    不按连续天数排(连续天数只是附加事实,UI 自己决定怎么用)。
    """

    trade_date: date | None = Field(
        description="最新有 sector_flow_daily 数据的交易日;空 → null"
    )
    sector_type: str = Field(description="请求的过滤类型:industry / concept / all")
    items: list[SectorPersistenceItem] = Field(
        description="最新日 main_inflow Top n;每条带 6 个事实字段"
    )


class RadarFundItem(BaseModel):
    """主力雷达单条基金项(PR16)。

    R3 红线:`score` 是客观雷达分(rank_score + inflow_score,封顶 9),
    不是买卖信号。`badge` 是身份标签(已持有/候选),不是操作指令。
    """

    fund_code: str
    fund_name: str
    matched_sector: str = Field(description="命中的中文板块标签,如 '半导体'")
    sector_code: str = Field(description="eastmoney BK code,如 'BK0490'")
    sector_rank: int = Field(ge=1, description="该板块在 industry 内的排名(1-based)")
    sector_main_inflow_wan: Decimal = Field(
        description="该板块主力净流入,万元(int_to_wan_yuan)"
    )
    sector_main_inflow_yi: Decimal = Field(
        description="该板块主力净流入,亿元(为前端方便直接显示;= main_inflow_wan / 10000)"
    )
    sector_change_pct: Decimal | None = Field(
        default=None,
        description="该板块涨跌幅,百分数表示(2.10 = 2.10%,跟 sectors/top 的 fraction 形式不同 — 跟用户的雷达 spec 对齐)"
    )
    score: int = Field(
        ge=0, le=9,
        description="客观雷达分(rank_score + inflow_score 封顶 9);不是买卖建议"
    )
    purity_score: int = Field(
        ge=0, le=9,
        description="基金主题贴合度(0-9);只表达基金跟当前强势板块的关联紧密度,"
                    "不是收益预测,不是买卖建议。同一板块多基金时用于区分纯度。"
    )
    badge: str = Field(description="'已持有' 或 '候选'")


class DashboardRadarResponse(BaseModel):
    """主力雷达响应(PR16)。

    V1 只支持 mode='intraday'(基于 intraday_sector_flow 最新 snapshot)。
    holdings/candidates 各自按 score DESC, sector_rank ASC 排,最多 n 条。
    """

    mode: str = Field(description="V1 固定 'intraday'")
    trade_date: date | None = Field(
        description="snapshot_time 的日期部分;空库 → null"
    )
    snapshot_time: datetime | None = Field(
        description="最新 snapshot 时刻(Asia/Shanghai 精确到分钟);空库 → null"
    )
    holdings: list[RadarFundItem] = Field(
        description="我的持仓中命中强势板块的基金"
    )
    candidates: list[RadarFundItem] = Field(
        description="非持仓但命中强势板块的基金(可视为候选池)"
    )


class SectorBriefItem(BaseModel):
    """AI 摘要里的单条板块简表(PR19)。

    main_inflow_yi:亿元(已 / 10000),正值流入,负值流出。
    change_pct:百分数(2.10 = 2.10%);跟 sectors/top 的 fraction 形式不同 —
    跟 radar / 雷达 spec 对齐(展示口径)。
    """

    sector_name: str
    main_inflow_yi: Decimal
    change_pct: Decimal | None = None


class AISummaryResponse(BaseModel):
    """AI 一句话结论(PR15 daily 缓存 + PR19 intraday 结构化)。

    优先 source='intraday'(读最新 intraday_sector_flow snapshot,
    规则生成,不调用任何 AI API);intraday 库空时 fallback 到
    source='daily_cached'(读 sector_flow_daily 最新交易日,同样规则化)。

    R3 兼容:全部规则生成,无 buy/sell/long/short/hold/加仓/减仓/继续持有/
    建议/推荐 等词;summary_text 只描述客观流向 + 持仓信号分布。

    旧字段(trade_date / summary / generated_at / cached)保留作向后兼容。
    """

    # ===== PR19 新增字段 =====
    source: str = Field(
        description="'intraday' | 'daily_cached'"
    )
    summary_text: str = Field(
        description="结构化短结论(PR19 渲染主体);跟旧 summary 字段语义近似"
    )
    inflow_top3: list[SectorBriefItem] = Field(
        default_factory=list,
        description="主力净流入 Top 3(industry,降序);intraday 优先,daily fallback"
    )
    outflow_top3: list[SectorBriefItem] = Field(
        default_factory=list,
        description="主力净流出 Top 3(industry,升序,只含 < 0)"
    )
    holding_stats: dict[str, int] = Field(
        default_factory=dict,
        description="signal_type → 持仓基金数(键:bullish/bearish/warning/neutral/not_applicable)"
    )
    data_date: date | None = Field(
        default=None,
        description="数据所属交易日(intraday=snapshot 当日;daily=sector_flow 最新交易日)"
    )
    data_time: str | None = Field(
        default=None,
        description="intraday snapshot 'HH:MM';daily_cached 时为 null"
    )

    # ===== 旧字段(向后兼容)=====
    trade_date: date | None = Field(
        description="(deprecated 改用 data_date)最新交易日;空 → null"
    )
    summary: str = Field(
        description="(deprecated 改用 summary_text)一句话结论"
    )
    generated_at: datetime = Field(
        description="本次返回内容的生成时刻(Asia/Shanghai)"
    )
    cached: bool = Field(
        description="只在 source='daily_cached' 且命中 24h 缓存时为 true;intraday 路径恒为 false"
    )
