<script setup lang="ts">
import { computed } from 'vue'
import type { FlowOrder } from '../../api/client'
import type { TopSectors } from '../../types'
import StaleBanner from './StaleBanner.vue'

// 今日资金 Top10 卡(Dashboard 重构 — 沿用 /sectors/top,order=inflow|outflow)。
//
// 原则:只显示客观计数 + 资金数额(亿元)。
// 不显示:评分 / 健康度 / 买卖建议 / 预测内容。
//
// 过滤(spec):
//   order='inflow'  → 只显示 main_inflow > 0(不补负数)
//   order='outflow' → 只显示 main_inflow < 0(不补正数)
// 后端 n 给宽点(30),前端按符号过滤再裁到 Top 10。

const props = defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: TopSectors | null
  error: string
  order: FlowOrder    // inflow | outflow — 决定标题 + 颜色
}>()

const filteredSectors = computed(() => {
  if (!props.data) return []
  return props.data.sectors.filter((s) => {
    const v = Number(s.main_inflow_wan)
    return props.order === 'inflow' ? v > 0 : v < 0
  })
})

function fmtYi(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return '—'
  const yi = Number(wanStr) / 10_000   // wan → 亿 = wan / 10000
  const sign = yi > 0 ? '+' : ''
  return `${sign}${yi.toFixed(1)}亿`
}

function inflowColor(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'text-gray-500'
  const n = Number(wanStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span
            class="inline-block w-1.5 h-4 rounded-sm"
            :class="order === 'inflow' ? 'bg-red-500' : 'bg-green-500'"
          ></span>
          {{ order === 'inflow' ? '今日资金流入' : '今日资金流出' }} Top10
        </h3>
        <span
          v-if="status === 'ready' && data?.trade_date"
          class="text-xs text-gray-400 tabular-nums"
        >
          截至 {{ data.trade_date }}
        </span>
      </div>
    </header>

    <div class="p-4">
      <StaleBanner :freshness="data?.freshness" />
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p
          v-if="filteredSectors.length === 0"
          class="text-gray-400 text-sm"
        >
          暂无{{ order === 'inflow' ? '净流入' : '净流出' }}板块
        </p>
        <ol v-else class="divide-y divide-gray-100">
          <li
            v-for="(s, i) in filteredSectors.slice(0, 10)"
            :key="s.sector_code"
            class="flex items-center justify-between gap-3 py-2"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span
                class="text-xs text-gray-400 tabular-nums w-6 text-right shrink-0"
              >
                #{{ i + 1 }}
              </span>
              <span class="text-sm text-gray-800 font-medium truncate">
                {{ s.sector_name }}
              </span>
            </div>
            <span
              class="text-sm font-semibold whitespace-nowrap tabular-nums"
              :class="inflowColor(s.main_inflow_wan)"
            >
              {{ fmtYi(s.main_inflow_wan) }}
            </span>
          </li>
        </ol>
      </template>
    </div>
  </section>
</template>
