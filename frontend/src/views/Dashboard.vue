<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { dashboardApi, type SectorTypeFilter } from '../api/client'
import AiSummary from '../components/dashboard/AiSummary.vue'
import HoldingMappings from '../components/dashboard/HoldingMappings.vue'
import MarketTemp from '../components/dashboard/MarketTemp.vue'
import MarketTopFunds from '../components/dashboard/MarketTopFunds.vue'
import MyHoldingsTable from '../components/dashboard/MyHoldingsTable.vue'
import TopSectorsCard from '../components/dashboard/TopSectors.vue'
import type {
  AISummary,
  HoldingsSummary,
  MarketSnapshot,
  TopFunds,
  TopSectors,
} from '../types'

// Dashboard V1(Phase 5.1)— 5 个卡片各自维护 {status, data, error}。
//
// 加载策略:5 个 Promise 并发发起,Promise.allSettled 不阻塞任何一个 —
// 每个卡片的 .then() 各自就地写自己的 ref,慢的(AI 可能 1-3s)不影响
// 已就绪的卡片渲染。allSettled 只是兜底"5 个都收尾后我也不关心"的语义。
//
// 容器(本文件)只管 fetch + 状态机 + Tab change → 重 fetch;
// 子组件只接 props,不发请求 — 边界清晰,容器替换数据源很容易。

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

// 给 HoldingMappings 用:全局板块 rank 映射(sector_type=all, n=100)。
// 单独拉一次,跟用户 Tab 状态(sectorsType)解耦 — 即使 Tab 在"行业",
// HoldingMappings 显示的 rank 仍是全局 across-types 排名,不会因
// Tab 切换变动。失败也不致命,fallback "—"。
const allSectorRanks = ref<Map<string, number>>(new Map())

// 持仓 fund_code 集合,客户端过滤 funds/top 用 — 保证 HoldingMappings
// 只显示用户持仓基金(而非整个 funds 表)。holdingsData 没到前是空 Set,
// 此时 HoldingMappings 显示空态"holdings 未加载"短暂占位,几百毫秒后
// holdings 到 → 自动填充。
const holdingCodes = computed<Set<string>>(() => {
  if (!holdingsData.value) return new Set()
  return new Set(holdingsData.value.holdings.map((h) => h.fund_code))
})

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
    // 全局板块 rank 字典(仅给 HoldingMappings 显示 "板块 #N" 用)
    // 失败时静默吞掉 — rank 显示就 fallback "—",不影响其他字段。
    dashboardApi.topSectors(100, 'all').then(
      (d) => {
        const m = new Map<string, number>()
        for (const s of d.sectors) m.set(s.sector_code, s.rank)
        allSectorRanks.value = m
      },
      () => { /* swallow */ },
    ),
  ])
})

// 所有显示辅助函数已分配到对应子组件(MarketTemp / AiSummary /
// TopSectors / TopFunds / MyHoldingsTable),容器只剩 fetch + 状态。
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

    <!-- 4. 最强 20 基金候选(市场维度,不过滤持仓)-->
    <MarketTopFunds
      :status="fundsStatus"
      :data="fundsData"
      :error="fundsError"
      :holding-codes="holdingCodes"
    />

    <!-- 5. 我的持仓映射(客户端过滤至 holdings)-->
    <HoldingMappings
      :status="fundsStatus"
      :data="fundsData"
      :error="fundsError"
      :holding-codes="holdingCodes"
      :sector-rank-by-code="allSectorRanks"
    />

    <!-- 5. 我的持仓分析 -->
    <MyHoldingsTable
      :status="holdingsStatus"
      :data="holdingsData"
      :error="holdingsError"
    />
  </div>
</template>
