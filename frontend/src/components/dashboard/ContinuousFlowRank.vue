<script setup lang="ts">
import type { SectorPersistenceLeadersResponse } from '../../types'
import DataTimeBadge from './DataTimeBadge.vue'
import StaleBanner from './StaleBanner.vue'

// 连续流入 / 连续流出 排行卡(Dashboard 重构)。
//
// 数据源:/api/dashboard/sectors/persistence/leaders?sort_by=continuous_inflow
// 或 continuous_outflow。
//
// R3 红线:只显示客观计数(连续天数);无评分 / 无建议 / 无预测。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: SectorPersistenceLeadersResponse | null
  error: string
  direction: 'inflow' | 'outflow'   // 颜色 + 标题
}>()

function fmtYi(yiStr: string | null | undefined): string {
  if (yiStr === null || yiStr === undefined) return '—'
  const yi = Number(yiStr)
  const sign = yi > 0 ? '+' : ''
  return `${sign}${yi.toFixed(1)}亿`
}

function inflowColor(yiStr: string | null | undefined): string {
  if (yiStr === null || yiStr === undefined) return 'text-gray-500'
  const n = Number(yiStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function daysOf(item: { continuous_inflow_days: number; continuous_outflow_days: number }, dir: 'inflow' | 'outflow'): number {
  return dir === 'inflow' ? item.continuous_inflow_days : item.continuous_outflow_days
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span
            class="inline-block w-1.5 h-4 rounded-sm"
            :class="direction === 'inflow' ? 'bg-red-500' : 'bg-green-500'"
          ></span>
          {{ direction === 'inflow' ? '连续流入排行' : '连续流出排行' }}
        </h3>
      </div>
      <DataTimeBadge
        v-if="status === 'ready'"
        class="mt-1"
        :time-meta="data?.time_meta"
        :freshness="data?.freshness"
      />
      <p class="text-xs text-gray-500 mt-1">
        基于 sector_flow_daily 历史
        {{ data?.min_days !== undefined ? `· ≥${data.min_days}天` : '' }}
      </p>
    </header>

    <div class="p-4">
      <StaleBanner :freshness="data?.freshness" />
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p
          v-if="data.items.length === 0"
          class="text-gray-400 text-sm"
        >
          暂无连续{{ direction === 'inflow' ? '流入' : '流出' }} ≥{{ data.min_days }}天的板块
        </p>
        <ol v-else class="divide-y divide-gray-100">
          <li
            v-for="(item, i) in data.items"
            :key="item.sector_code"
            class="flex items-center justify-between gap-3 py-2"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span
                class="text-xs text-gray-400 tabular-nums w-6 text-right shrink-0"
              >
                #{{ i + 1 }}
              </span>
              <span class="text-sm text-gray-800 font-medium truncate">
                {{ item.sector_name }}
              </span>
            </div>
            <div class="flex items-center gap-3 shrink-0">
              <span
                class="text-sm font-semibold tabular-nums"
                :class="direction === 'inflow' ? 'text-red-600' : 'text-green-600'"
              >
                连续 {{ daysOf(item, direction) }} 天
              </span>
              <span
                class="text-xs tabular-nums w-16 text-right"
                :class="inflowColor(item.latest_main_inflow_yi)"
              >
                {{ fmtYi(item.latest_main_inflow_yi) }}
              </span>
            </div>
          </li>
        </ol>
      </template>
    </div>
  </section>
</template>
