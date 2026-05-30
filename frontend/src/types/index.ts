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

export interface AISummary {
  trade_date: string | null
  summary: string
  generated_at: string               // ISO datetime
  cached: boolean
}
