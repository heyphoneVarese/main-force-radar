<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardApi } from '../api/client'
import AiSummary from '../components/dashboard/AiSummary.vue'
import MarketTemp from '../components/dashboard/MarketTemp.vue'
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

onMounted(() => {
  void Promise.allSettled([
    dashboardApi.market().then(
      (d) => { marketData.value = d; marketStatus.value = 'ready' },
      (e) => { marketError.value = _errMsg(e); marketStatus.value = 'error' },
    ),
    dashboardApi.topSectors().then(
      (d) => { sectorsData.value = d; sectorsStatus.value = 'ready' },
      (e) => { sectorsError.value = _errMsg(e); sectorsStatus.value = 'error' },
    ),
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

function fmtPct(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'n/a'
  const n = Number(decStr) * 100
  const sign = n > 0 ? '+' : ''   // 负号 Number.toFixed 自带
  return `${sign}${n.toFixed(2)}%`
}

function fmtYi(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'n/a'
  const yi = Number(wanStr) / 10_000   // 万元 → 亿
  const sign = yi > 0 ? '+' : ''
  return `${sign}${yi.toFixed(1)}亿`
}

function pctColor(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'text-gray-500'
  const n = Number(decStr)
  if (n > 0) return 'text-red-600'   // A 股红涨绿跌惯例
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function inflowColor(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'text-gray-500'
  const n = Number(wanStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

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
    <section class="bg-white rounded-lg shadow-sm p-4 border">
      <h3 class="text-base font-semibold mb-3 text-gray-900">Top 20 板块</h3>
      <p v-if="sectorsStatus === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="sectorsStatus === 'error'" class="text-red-500 text-sm">
        ⚠ {{ sectorsError }}
      </p>
      <template v-else-if="sectorsData">
        <p v-if="sectorsData.sectors.length === 0" class="text-gray-400 text-sm">暂无数据</p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2">
            截至 {{ sectorsData.trade_date }} · 共 {{ sectorsData.sectors.length }} 条
          </p>
          <ul class="text-sm space-y-1">
            <li
              v-for="s in sectorsData.sectors.slice(0, 10)"
              :key="s.sector_code"
              class="flex items-center justify-between gap-3 py-1 border-b last:border-b-0"
            >
              <span class="text-gray-700 truncate">
                <span class="text-gray-400 text-xs mr-2">#{{ s.rank }}</span>
                {{ s.sector_name }}
              </span>
              <span class="text-right whitespace-nowrap">
                <span :class="inflowColor(s.main_inflow_wan)">
                  {{ fmtYi(s.main_inflow_wan) }}
                </span>
                <span class="text-xs text-gray-400 ml-2" :class="pctColor(s.change_pct)">
                  {{ fmtPct(s.change_pct) }}
                </span>
              </span>
            </li>
          </ul>
          <p
            v-if="sectorsData.sectors.length > 10"
            class="text-xs text-gray-400 mt-2"
          >
            显示前 10;PR9 会渲染完整 Top 20
          </p>
        </template>
      </template>
    </section>

    <!-- 4. Top 20 基金 -->
    <section class="bg-white rounded-lg shadow-sm p-4 border">
      <h3 class="text-base font-semibold mb-3 text-gray-900">Top 20 基金</h3>
      <p v-if="fundsStatus === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="fundsStatus === 'error'" class="text-red-500 text-sm">
        ⚠ {{ fundsError }}
      </p>
      <template v-else-if="fundsData">
        <p v-if="fundsData.funds.length === 0" class="text-gray-400 text-sm">
          暂无数据(基金需先在 funds 表 + sector_aliases 映射 + sector_flow 当日有数据)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2">
            截至 {{ fundsData.trade_date }} · 共 {{ fundsData.funds.length }} 条
          </p>
          <ul class="text-sm space-y-1">
            <li
              v-for="f in fundsData.funds.slice(0, 10)"
              :key="f.fund_code"
              class="flex items-center justify-between gap-3 py-1 border-b last:border-b-0"
            >
              <span class="text-gray-700 truncate min-w-0">
                <span class="text-gray-400 text-xs mr-2">#{{ f.rank }}</span>
                {{ f.fund_name }}
              </span>
              <span class="text-right whitespace-nowrap">
                <span :class="inflowColor(f.main_inflow_wan)">
                  {{ fmtYi(f.main_inflow_wan) }}
                </span>
                <span class="text-xs text-gray-400 ml-2">score {{ f.score }}/9</span>
              </span>
            </li>
          </ul>
          <p
            v-if="fundsData.funds.length > 10"
            class="text-xs text-gray-400 mt-2"
          >
            显示前 10;PR9 会渲染完整 Top 20
          </p>
        </template>
      </template>
    </section>

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
