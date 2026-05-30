<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardApi, type SectorTypeFilter } from '../api/client'
import AiSummary from '../components/dashboard/AiSummary.vue'
import MarketTemp from '../components/dashboard/MarketTemp.vue'
import TopFundsCard from '../components/dashboard/TopFunds.vue'
import TopSectorsCard from '../components/dashboard/TopSectors.vue'
import type {
  AISummary,
  HoldingSignal,
  HoldingsSummary,
  MarketSnapshot,
  TopFunds,
  TopSectors,
} from '../types'

// PR7 骨架:5 个独立卡片,各自维护 loading/ready/error 状态。
//
// 加载策略:5 个 Promise 并发发起,Promise.allSettled 不阻塞任何一个 —
// 每个卡片的 .then() 各自就地写自己的 ref,慢的(AI 可能 1-3s)不影响
// 已就绪的卡片渲染。allSettled 只是兜底"5 个都收尾后我也不关心"的语义。
//
// PR8-10 会把每个 section 抽成独立组件 + 富化样式。本 PR 重点:接口贯通 +
// 状态机正确 + 不抛 unhandled rejection。

type Status = 'loading' | 'ready' | 'error'

const marketStatus = ref<Status>('loading')
const marketData = ref<MarketSnapshot | null>(null)
const marketError = ref('')

const sectorsStatus = ref<Status>('loading')
const sectorsData = ref<TopSectors | null>(null)
const sectorsError = ref('')
const sectorsType = ref<SectorTypeFilter>('industry')

const holdingsStatus = ref<Status>('loading')
const holdingsData = ref<HoldingsSummary | null>(null)
const holdingsError = ref('')

const fundsStatus = ref<Status>('loading')
const fundsData = ref<TopFunds | null>(null)
const fundsError = ref('')

const aiStatus = ref<Status>('loading')
const aiData = ref<AISummary | null>(null)
const aiError = ref('')

function _errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// sectors 单独抽出来 — 给 tab 切换复用。状态机:点 tab 立刻把 status
// 切回 'loading',旧 data 保留显示直到新数据到(避免闪烁)。
function loadSectors(t: SectorTypeFilter): Promise<void> {
  sectorsStatus.value = 'loading'
  return dashboardApi.topSectors(20, t).then(
    (d) => { sectorsData.value = d; sectorsStatus.value = 'ready' },
    (e) => { sectorsError.value = _errMsg(e); sectorsStatus.value = 'error' },
  )
}

function onSectorsTypeChange(t: SectorTypeFilter): void {
  if (t === sectorsType.value) return
  sectorsType.value = t
  void loadSectors(t)
}

onMounted(() => {
  void Promise.allSettled([
    dashboardApi.market().then(
      (d) => { marketData.value = d; marketStatus.value = 'ready' },
      (e) => { marketError.value = _errMsg(e); marketStatus.value = 'error' },
    ),
    loadSectors(sectorsType.value),
    dashboardApi.holdingsSummary().then(
      (d) => { holdingsData.value = d; holdingsStatus.value = 'ready' },
      (e) => { holdingsError.value = _errMsg(e); holdingsStatus.value = 'error' },
    ),
    dashboardApi.topFunds().then(
      (d) => { fundsData.value = d; fundsStatus.value = 'ready' },
      (e) => { fundsError.value = _errMsg(e); fundsStatus.value = 'error' },
    ),
    dashboardApi.aiSummary().then(
      (d) => { aiData.value = d; aiStatus.value = 'ready' },
      (e) => { aiError.value = _errMsg(e); aiStatus.value = 'error' },
    ),
  ])
})

// ===== 显示辅助 =====
// fmtPct / fmtYi / pctColor / inflowColor 已分别迁到使用它们的子组件
// (MarketTemp / TopSectors / TopFunds);本文件只剩 holdings 卡用到的
// signalCounts(PR10 会把它也带走)。

function signalCounts(holdings: HoldingSignal[]): Array<[string, number]> {
  const counts: Record<string, number> = {}
  for (const h of holdings) {
    counts[h.signal_type] = (counts[h.signal_type] || 0) + 1
  }
  // 固定顺序,前端别因为对象 key 顺序漂移
  const order = ['bullish', 'warning', 'neutral', 'bearish', 'not_applicable']
  return order
    .filter((k) => k in counts)
    .map((k) => [k, counts[k]] as [string, number])
}
</script>

<template>
  <div class="space-y-4">
    <!-- 1. 今日市场温度 -->
    <MarketTemp :status="marketStatus" :data="marketData" :error="marketError" />

    <!-- 2. AI 一句话结论 -->
    <AiSummary :status="aiStatus" :data="aiData" :error="aiError" />

    <!-- 3. Top 20 板块 -->
    <TopSectorsCard
      :status="sectorsStatus"
      :data="sectorsData"
      :error="sectorsError"
      :current-type="sectorsType"
      @change-type="onSectorsTypeChange"
    />

    <!-- 4. Top 20 基金 -->
    <TopFundsCard
      :status="fundsStatus"
      :data="fundsData"
      :error="fundsError"
    />

    <!-- 5. 我的持仓分析 -->
    <section class="bg-white rounded-lg shadow-sm p-4 border">
      <h3 class="text-base font-semibold mb-3 text-gray-900">我的持仓分析</h3>
      <p v-if="holdingsStatus === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="holdingsStatus === 'error'" class="text-red-500 text-sm">
        ⚠ {{ holdingsError }}
      </p>
      <template v-else-if="holdingsData">
        <p v-if="holdingsData.holdings.length === 0" class="text-gray-400 text-sm">
          暂无持仓(去 Holdings 页添加)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-3">
            共 {{ holdingsData.holdings.length }} 只持仓 · 截至
            {{ holdingsData.trade_date ?? '—' }}
          </p>
          <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div
              v-for="[sig, count] in signalCounts(holdingsData.holdings)"
              :key="sig"
              class="border rounded p-2 text-center"
            >
              <div class="text-xs text-gray-500">{{ sig }}</div>
              <div class="text-lg font-semibold text-gray-800">{{ count }}</div>
            </div>
          </div>
          <p class="text-xs text-gray-400 mt-3">
            PR10 会渲染明细表(每只基金的 via_sector / score / main_inflow)
          </p>
        </template>
      </template>
    </section>
  </div>
</template>
