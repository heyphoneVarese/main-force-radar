<script setup lang="ts">
import { computed } from 'vue'
import type { AISummary } from '../../types'
import StaleBanner from './StaleBanner.vue'

// AI 结论卡 — PR19 结构化重构。
//
// 渲染逻辑:
//   source='intraday'      → 标题 "AI 结论 · 盘中" + badge "盘中" + 副标题 "更新时间 HH:MM"
//   source='daily_cached'  → 标题 "AI 结论 · 收盘缓存" + badge "cached" + 副标题 "数据 YYYY-MM-DD"
//
// R3 红线:模板里所有文字 + 函数返回都只描述客观流向 / 持仓信号分布。
// 绝不出现 buy/sell/long/short/hold/加仓/减仓/继续持有/建议/推荐 等词。

const props = defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: AISummary | null
  error: string
}>()

const isIntraday = computed(() => props.data?.source === 'intraday')

const titleSuffix = computed(() =>
  isIntraday.value ? '盘中' : '收盘缓存'
)

const subtitleText = computed(() => {
  if (!props.data) return ''
  if (isIntraday.value && props.data.data_time) {
    return `更新时间 ${props.data.data_time}`
  }
  if (props.data.data_date) {
    return `数据 ${props.data.data_date}`
  }
  return ''
})

const conclusionText = computed(() => {
  if (!props.data) return ''
  if (isIntraday.value) {
    const names = props.data.inflow_top3.map((s) => s.sector_name)
    if (names.length === 0) return ''
    return `当前资金偏向:${names.join(' / ')}`
  }
  return '当前显示收盘缓存数据,非盘中实时'
})

// 持仓状态 chip 顺序:稳定且语义化(red→orange→green→gray)
const SIGNAL_ORDER: string[] = [
  'bullish', 'warning', 'bearish', 'neutral', 'not_applicable',
]

const holdingStatsOrdered = computed<Array<[string, number]>>(() => {
  if (!props.data) return []
  const stats = props.data.holding_stats || {}
  return SIGNAL_ORDER
    .filter((k) => (stats[k] ?? 0) > 0)
    .map((k) => [k, stats[k]] as [string, number])
})

const hasInflowTop3 = computed(() => (props.data?.inflow_top3.length ?? 0) > 0)
const hasOutflowTop3 = computed(() => (props.data?.outflow_top3.length ?? 0) > 0)
const hasHoldingStats = computed(() => holdingStatsOrdered.value.length > 0)

function fmtInflow(yi: string): string {
  const n = Number(yi)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function inflowClass(yi: string): string {
  const n = Number(yi)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function signalChipClass(sig: string): string {
  switch (sig) {
    case 'bullish':
      return 'bg-red-50 text-red-700 border-red-200'
    case 'bearish':
      return 'bg-green-50 text-green-700 border-green-200'
    case 'warning':
      return 'bg-orange-50 text-orange-700 border-orange-200'
    case 'neutral':
      return 'bg-gray-100 text-gray-600 border-gray-200'
    case 'not_applicable':
      return 'bg-gray-50 text-gray-400 border-gray-100'
    default:
      return 'bg-gray-100 text-gray-600 border-gray-200'
  }
}

const sourceBadgeText = computed(() =>
  isIntraday.value ? '盘中' : 'cached'
)

const sourceBadgeClass = computed(() =>
  isIntraday.value
    ? 'bg-blue-50 text-blue-700 border-blue-200'
    : 'bg-gray-100 text-gray-500 border-gray-200'
)
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2 min-w-0">
          <span class="inline-block w-1.5 h-4 bg-blue-500 rounded-sm shrink-0"></span>
          AI 结论 ·
          <span :class="isIntraday ? 'text-blue-700' : 'text-gray-600'">
            {{ titleSuffix }}
          </span>
        </h3>
        <span
          v-if="status === 'ready' && data"
          class="text-xs px-2 py-0.5 rounded-full border whitespace-nowrap shrink-0"
          :class="sourceBadgeClass"
          :title="
            isIntraday
              ? '基于最新 intraday snapshot 实时计算'
              : '基于最新 sector_flow_daily,可能与盘中实时不同步'
          "
        >
          {{ sourceBadgeText }}
        </span>
      </div>
      <p
        v-if="status === 'ready' && subtitleText"
        class="text-xs text-gray-400 tabular-nums mt-0.5"
      >
        {{ subtitleText }}
      </p>
    </header>

    <div class="p-4 space-y-4">
      <StaleBanner :freshness="data?.freshness" />
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">⚠ {{ error }}</p>
      <template v-else-if="data">
        <!-- A. 主力流入 Top3 -->
        <div v-if="hasInflowTop3">
          <h4 class="text-xs font-medium text-gray-600 mb-1.5">
            主力流入 Top3
          </h4>
          <ul class="space-y-0.5">
            <li
              v-for="(s, i) in data.inflow_top3"
              :key="`in-${s.sector_name}-${i}`"
              class="flex items-center justify-between gap-3 text-sm tabular-nums"
            >
              <span class="flex items-center gap-2 min-w-0">
                <span class="text-xs text-gray-400 w-6 text-right shrink-0">
                  #{{ i + 1 }}
                </span>
                <span class="text-gray-700 truncate">{{ s.sector_name }}</span>
              </span>
              <span
                class="font-semibold whitespace-nowrap"
                :class="inflowClass(s.main_inflow_yi)"
              >
                {{ fmtInflow(s.main_inflow_yi) }}
              </span>
            </li>
          </ul>
        </div>

        <!-- B. 主力流出 Top3 -->
        <div v-if="hasOutflowTop3">
          <h4 class="text-xs font-medium text-gray-600 mb-1.5">
            主力流出 Top3
          </h4>
          <ul class="space-y-0.5">
            <li
              v-for="(s, i) in data.outflow_top3"
              :key="`out-${s.sector_name}-${i}`"
              class="flex items-center justify-between gap-3 text-sm tabular-nums"
            >
              <span class="flex items-center gap-2 min-w-0">
                <span class="text-xs text-gray-400 w-6 text-right shrink-0">
                  #{{ i + 1 }}
                </span>
                <span class="text-gray-700 truncate">{{ s.sector_name }}</span>
              </span>
              <span
                class="font-semibold whitespace-nowrap"
                :class="inflowClass(s.main_inflow_yi)"
              >
                {{ fmtInflow(s.main_inflow_yi) }}
              </span>
            </li>
          </ul>
        </div>

        <!-- C. 持仓状态 chips -->
        <div v-if="hasHoldingStats">
          <h4 class="text-xs font-medium text-gray-600 mb-1.5">
            持仓状态
          </h4>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="[sig, count] in holdingStatsOrdered"
              :key="sig"
              class="text-xs px-2 py-0.5 rounded border tabular-nums whitespace-nowrap"
              :class="signalChipClass(sig)"
            >
              {{ sig }} {{ count }}
            </span>
          </div>
        </div>

        <!-- 底部短结论 -->
        <p
          v-if="conclusionText"
          class="text-xs text-gray-500 border-t pt-2 mt-2"
        >
          {{ conclusionText }}
        </p>

        <!-- 空态:三块全空 -->
        <p
          v-if="!hasInflowTop3 && !hasOutflowTop3 && !hasHoldingStats"
          class="text-gray-400 text-sm"
        >
          {{ data.summary_text }}
        </p>
      </template>
    </div>
  </section>
</template>
