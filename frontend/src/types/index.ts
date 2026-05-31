// 后端 Pydantic 模型的镜像。金额/份额走 Decimal-as-string(R1)。

export interface Fund {
  fund_code: string
  fund_name: string
  fund_type: string
  company: string | null
  manager: string | null
  establish_date: string | null
  tracking_target: string | null
  related_sectors: string[] | null
  created_at: string
  updated_at: string
}

export interface Holding {
  id: number
  fund_code: string
  cost_nav: string // Decimal 字符串,如 "1.5234"
  shares: string   // Decimal 字符串,如 "1000.5"
  bought_at: string // ISO date "YYYY-MM-DD"
  note: string | null
  created_at: string
  updated_at: string
}

export interface HoldingCreate {
  fund_code: string
  cost_nav: string
  shares: string
  bought_at: string
  note: string | null
}

export interface HoldingUpdate {
  cost_nav?: string
  shares?: string
  bought_at?: string
  note?: string | null
}

// 新增基金入参(POST /api/funds)。
// 后端 FundBase 还有 company / manager / establish_date / tracking_target 等
// 可选字段;PR13 UI 不暴露,默认 null。fund_type 必填(后端 min_length=1),
// UI 不让用户填,提交时 hardcode "其他"。
export interface FundCreate {
  fund_code: string
  fund_name: string
  fund_type: string
  related_sectors?: string[] | null
}

// ===== Dashboard responses (镜像 backend Pydantic) =====
// 所有 Decimal 字段都是 string 透传(跟 Holding.cost_nav 一致语义)。
// change_pct / main_inflow_pct 是 fraction("0.0066" = 0.66%),前端 ×100 显示。

export interface MarketIndex {
  index_code: string                 // sh000001 / sz399001 / sz399006 / sh000300
  index_name: string
  trade_date: string                 // "YYYY-MM-DD"
  close: string                      // Decimal 点位
  change_pct: string                 // fraction
  turnover_wan: string | null        // Decimal 万元;sina 源无 amount 时 null
}

export interface MarketSnapshot {
  trade_date: string | null
  indices: MarketIndex[]
}

export interface SectorFlow {
  rank: number
  sector_code: string                // BK0727
  sector_name: string
  sector_type: string                // industry / concept / region
  main_inflow_wan: string            // Decimal 万元;可负
  main_inflow_pct: string | null     // fraction
  change_pct: string | null
}

export interface TopSectors {
  trade_date: string | null
  sector_type: 'industry' | 'concept' | 'all'
  sectors: SectorFlow[]
}

// PR20 + PR21:板块连续天数事实(R3:全部是客观计数,不是评分)
export interface SectorPersistenceItem {
  rank: number
  sector_code: string
  sector_name: string
  sector_type: string
  main_inflow_yi: string                  // Decimal 亿元

  continuous_inflow_days: number          // 连续净流入天数
  continuous_outflow_days: number         // 连续净流出天数
  continuous_top20_days: number           // 连续 Top20 天数

  // PR21 新增:5/10 日窗口
  last_5_inflow_days: number
  last_10_inflow_days: number
  last_5_outflow_days: number
  last_10_outflow_days: number
  last_5_top20_days: number
  last_10_top20_days: number

  // PR20 原 20 日窗口(保留兼容)
  last_20_top20_days: number
  last_20_inflow_days: number
  last_20_outflow_days: number
}

export interface SectorPersistenceResponse {
  trade_date: string | null
  sector_type: 'industry' | 'concept' | 'all'
  items: SectorPersistenceItem[]
}

export interface IntradayTopSectors {
  trade_date: string | null
  snapshot_time: string | null   // ISO datetime;最新 snapshot 时刻
  sector_type: 'industry' | 'concept' | 'all'
  sectors: SectorFlow[]
}

export interface HoldingSignal {
  fund_code: string
  fund_name: string | null
  related_sectors: string[]
  signal_type: 'bullish' | 'bearish' | 'warning' | 'neutral' | 'not_applicable'
  persistence_score: number          // 0-9
  via_sector: string | null          // BK code
  main_inflow_wan: string | null     // Decimal 万元
  change_pct: string | null          // fraction
  reason: string
}

export interface HoldingsSummary {
  trade_date: string | null
  holdings: HoldingSignal[]
}

export interface MatchedSector {
  sector_code: string
  sector_name: string
}

export interface TopFund {
  rank: number
  fund_code: string
  fund_name: string
  related_sectors: string[]
  matched_sectors: MatchedSector[]
  score: number                      // 0-9 持续性
  main_inflow_wan: string            // Decimal 万元
  change_pct: string | null
  reason: string
}

export interface TopFunds {
  trade_date: string | null
  funds: TopFund[]
}

export interface SectorBriefItem {
  sector_name: string
  main_inflow_yi: string             // Decimal 亿元
  change_pct: string | null          // Decimal 百分数
}

export interface AISummary {
  // PR19 新字段
  source: 'intraday' | 'daily_cached'
  summary_text: string
  inflow_top3: SectorBriefItem[]
  outflow_top3: SectorBriefItem[]
  holding_stats: Record<string, number>   // signal_type → count
  data_date: string | null
  data_time: string | null           // "HH:MM" intraday only

  // 旧字段(向后兼容,新 UI 不用)
  trade_date: string | null
  summary: string
  generated_at: string
  cached: boolean
}

// ===== 主力雷达(PR16)=====
// R3 红线:badge 只有 '已持有' / '候选',score 只是客观雷达分。
// sector_change_pct 是百分数(2.10 = 2.10%),跟 SectorFlow.change_pct 的
// fraction(0.0210)刻意不同,雷达 spec 这么要求。

export interface RadarFundItem {
  fund_code: string
  fund_name: string
  matched_sector: string             // 命中的中文标签
  sector_code: string                // BK code
  sector_rank: number                // 1-based
  sector_main_inflow_wan: string     // Decimal 万元
  sector_main_inflow_yi: string      // Decimal 亿元(已 / 10000)
  sector_change_pct: string | null   // Decimal 百分数
  score: number                      // 0..9 板块强势分
  purity_score: number               // 0..9 基金主题贴合度(PR17)
  badge: '已持有' | '候选'
}

export interface DashboardRadarResponse {
  mode: 'intraday'
  trade_date: string | null
  snapshot_time: string | null       // ISO datetime
  holdings: RadarFundItem[]
  candidates: RadarFundItem[]
}
