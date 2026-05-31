// 极简 fetch 封装。后端错误 detail 透传到 Error.message,UI 层用 ElMessage 展示。
import type {
  AISummary,
  DashboardRadarResponse,
  Fund,
  FundCreate,
  Holding,
  HoldingCreate,
  HoldingSectorAlertsResponse,
  HoldingsSummary,
  HoldingUpdate,
  IntradayTopSectors,
  MarketSnapshot,
  SectorPersistenceLeadersResponse,
  SectorPersistenceResponse,
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

export const dashboardApi = {
  market: () => jsonFetch<MarketSnapshot>(`${BASE}/dashboard/market`),
  topSectors: (n: number = 20, sectorType: SectorTypeFilter = 'industry') =>
    jsonFetch<TopSectors>(
      `${BASE}/dashboard/sectors/top?n=${n}&sector_type=${sectorType}`
    ),
  intradayTopSectors: (n: number = 20, sectorType: SectorTypeFilter = 'industry') =>
    jsonFetch<IntradayTopSectors>(
      `${BASE}/dashboard/intraday/sectors/top?n=${n}&sector_type=${sectorType}`
    ),
  holdingsSummary: () =>
    jsonFetch<HoldingsSummary>(`${BASE}/dashboard/holdings-summary`),
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
  sectorPersistenceLeaders: (
    n: number = 10,
    sectorType: SectorTypeFilter = 'industry',
    minDays: number = 3,
  ) =>
    jsonFetch<SectorPersistenceLeadersResponse>(
      `${BASE}/dashboard/sectors/persistence/leaders` +
      `?n=${n}&sector_type=${sectorType}&min_days=${minDays}`
    ),
  // PR23:持仓-板块事实预警
  holdingSectorAlerts: (n: number = 10) =>
    jsonFetch<HoldingSectorAlertsResponse>(
      `${BASE}/dashboard/holding-sector-alerts?n=${n}`
    ),
}
