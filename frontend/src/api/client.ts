// 极简 fetch 封装。后端错误 detail 透传到 Error.message,UI 层用 ElMessage 展示。
import type {
  AISummary,
  CapitalMigrationResponse,
  DashboardRadarResponse,
  Fund,
  FundCreate,
  Holding,
  HoldingsCapitalMigrationResponse,
  HoldingCreate,
  HoldingFactsSummary,
  HoldingSectorAlertsResponse,
  HoldingsSummary,
  HoldingUpdate,
  IntradayTopSectors,
  MarketSnapshot,
  SectorPersistenceLeadersResponse,
  SectorPersistenceResponse,
  SectorTrendsResponse,
  TopFunds,
  TopSectors,
} from '../types'

const BASE = '/api' // vite proxy 转到 localhost:8000

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  // 只在带 body 时才发 Content-Type:application/json。
  // DELETE 没有 body,带上这个 header 在 iOS Safari 同源 fetch 下偶发
  // "Load failed" 网络层错(疑似触发非必要 preflight)。
  const headers: Record<string, string> = init?.body
    ? { 'Content-Type': 'application/json' }
    : {}
  const res = await fetch(url, {
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      // ignore parse error
    }
    throw new Error(`HTTP ${res.status}: ${detail}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const holdingsApi = {
  list: () => jsonFetch<Holding[]>(`${BASE}/holdings`),
  create: (body: HoldingCreate) =>
    jsonFetch<Holding>(`${BASE}/holdings`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  update: (fundCode: string, body: HoldingUpdate) =>
    jsonFetch<Holding>(`${BASE}/holdings/${fundCode}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  remove: (fundCode: string) =>
    jsonFetch<void>(`${BASE}/holdings/${fundCode}`, { method: 'DELETE' }),
}

export const fundsApi = {
  list: () => jsonFetch<Fund[]>(`${BASE}/funds`),
  create: (body: FundCreate) =>
    jsonFetch<Fund>(`${BASE}/funds`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}

// ===== Dashboard 5 个端点(Phase 5.1 PR7) =====
//
// 跟后端 Pydantic 约定:整数 money / pct 已经在后端转 Decimal 字符串,
// 前端只负责字符串 → Number 显示。空数据时 trade_date=null,子列表=[]。

export type SectorTypeFilter = 'industry' | 'concept' | 'all'
export type FlowOrder = 'inflow' | 'outflow'
export type LeaderSortBy =
  | 'continuous_top20'
  | 'continuous_inflow'
  | 'continuous_outflow'

export const dashboardApi = {
  market: () => jsonFetch<MarketSnapshot>(`${BASE}/dashboard/market`),
  topSectors: (
    n: number = 20,
    sectorType: SectorTypeFilter = 'industry',
    order: FlowOrder = 'inflow',
  ) =>
    jsonFetch<TopSectors>(
      `${BASE}/dashboard/sectors/top?n=${n}&sector_type=${sectorType}` +
      `&order=${order}`
    ),
  intradayTopSectors: (n: number = 20, sectorType: SectorTypeFilter = 'industry') =>
    jsonFetch<IntradayTopSectors>(
      `${BASE}/dashboard/intraday/sectors/top?n=${n}&sector_type=${sectorType}`
    ),
  holdingsSummary: () =>
    jsonFetch<HoldingsSummary>(`${BASE}/dashboard/holdings-summary`),
  // PR26:持仓-事实摘要(替代情绪系统)
  holdingsFacts: () =>
    jsonFetch<HoldingFactsSummary>(`${BASE}/dashboard/holdings-facts`),
  topFunds: (n: number = 20) =>
    jsonFetch<TopFunds>(`${BASE}/dashboard/funds/top?n=${n}`),
  aiSummary: () => jsonFetch<AISummary>(`${BASE}/dashboard/ai-summary`),
  radar: (mode: 'intraday' = 'intraday', n: number = 20) =>
    jsonFetch<DashboardRadarResponse>(
      `${BASE}/dashboard/radar?mode=${mode}&n=${n}`
    ),
  sectorPersistence: (
    n: number = 20,
    sectorType: SectorTypeFilter = 'industry',
  ) =>
    jsonFetch<SectorPersistenceResponse>(
      `${BASE}/dashboard/sectors/persistence?n=${n}&sector_type=${sectorType}`
    ),
  // PR22 + PR24:连续Top20排行榜(min_days 默认 3,过滤刚上榜板块)
  // Dashboard 重构:加 sortBy 支持 continuous_inflow / continuous_outflow
  sectorPersistenceLeaders: (
    n: number = 10,
    sectorType: SectorTypeFilter = 'industry',
    minDays: number = 3,
    sortBy: LeaderSortBy = 'continuous_top20',
  ) =>
    jsonFetch<SectorPersistenceLeadersResponse>(
      `${BASE}/dashboard/sectors/persistence/leaders` +
      `?n=${n}&sector_type=${sectorType}&min_days=${minDays}` +
      `&sort_by=${sortBy}`
    ),
  // PR23:持仓-板块事实预警
  holdingSectorAlerts: (n: number = 10) =>
    jsonFetch<HoldingSectorAlertsResponse>(
      `${BASE}/dashboard/holding-sector-alerts?n=${n}`
    ),
  // PR25:20 天资金趋势(复用 leaders 选板块)
  sectorTrends: (
    n: number = 10,
    sectorType: SectorTypeFilter = 'industry',
  ) =>
    jsonFetch<SectorTrendsResponse>(
      `${BASE}/dashboard/sector-trends?n=${n}&sector_type=${sectorType}`
    ),
  capitalMigration: (
    n: number = 10,
    sectorType: SectorTypeFilter = 'industry',
    window: number = 20,
  ) =>
    jsonFetch<CapitalMigrationResponse>(
      `${BASE}/dashboard/capital-migration?n=${n}&sector_type=${sectorType}` +
      `&window=${window}`
    ),
  holdingsCapitalMigration: (window: number = 20) =>
    jsonFetch<HoldingsCapitalMigrationResponse>(
      `${BASE}/dashboard/holdings/capital-migration?window=${window}`
    ),
}
