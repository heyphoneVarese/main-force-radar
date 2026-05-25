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
