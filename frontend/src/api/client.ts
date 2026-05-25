// 极简 fetch 封装。后端错误 detail 透传到 Error.message,UI 层用 ElMessage 展示。
import type { Fund, Holding, HoldingCreate, HoldingUpdate } from '../types'

const BASE = '/api' // vite proxy 转到 localhost:8000

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
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
}
