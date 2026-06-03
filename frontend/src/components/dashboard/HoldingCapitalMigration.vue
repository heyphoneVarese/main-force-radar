<script setup lang="ts">
import type {
  HoldingCapitalMigrationItem,
  HoldingsCapitalMigrationResponse,
} from '../../types'
import StaleBanner from './StaleBanner.vue'

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: HoldingsCapitalMigrationResponse | null
  error: string
}>()

function fmtYi(v: string | null): string {
  if (v === null) return '--'
  const n = Number(v)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function valueColor(v: string | null): string {
  if (v === null) return 'text-gray-500'
  const n = Number(v)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function statusText(item: HoldingCapitalMigrationItem): string {
  if (item.mapping_status === 'low_confidence') return '待确认映射'
  if (item.mapping_status === 'unmapped') return '未映射'
  if (item.mapping_status === 'not_applicable') return '不适用'
  if (item.migration_status === 'strengthening') return '资金加强'
  if (item.migration_status === 'weakening') return '资金减弱'
  if (item.migration_status === 'inflowing') return '后半段流入'
  if (item.migration_status === 'outflowing') return '后半段流出'
  if (item.migration_status === 'mixed') return '震荡'
  return '数据不足'
}

function badgeClass(item: HoldingCapitalMigrationItem): string {
  if (item.mapping_status !== 'verified') return 'bg-gray-100 text-gray-600'
  if (item.migration_status === 'strengthening' || item.migration_status === 'inflowing') {
    return 'bg-red-50 text-red-700'
  }
  if (item.migration_status === 'weakening' || item.migration_status === 'outflowing') {
    return 'bg-green-50 text-green-700'
  }
  return 'bg-gray-100 text-gray-700'
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-teal-500 rounded-sm"></span>
        持仓主线资金变化
      </h3>
      <p class="text-xs text-gray-500 mt-1">
        资金状态变化。仅展示最近20个交易日历史资金事实，不构成投资建议。
      </p>
    </header>

    <div class="p-4">
      <StaleBanner :freshness="data?.freshness" />
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.holdings.length === 0" class="text-gray-400 text-sm">
          暂无持仓数据
        </p>
        <div v-else class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-left text-xs text-gray-500 border-b">
                <th class="py-2 pr-3 font-medium">基金</th>
                <th class="py-2 pr-3 font-medium">映射主线</th>
                <th class="py-2 pr-3 font-medium">状态</th>
                <th class="py-2 pr-3 font-medium text-right">前半</th>
                <th class="py-2 pr-3 font-medium text-right">后半</th>
                <th class="py-2 pr-3 font-medium text-right">变化</th>
                <th class="py-2 font-medium text-right">样本</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-for="item in data.holdings" :key="item.fund_code">
                <td class="py-2 pr-3">
                  <div class="font-medium text-gray-900 max-w-[220px] truncate">
                    {{ item.fund_name }}
                  </div>
                  <div class="text-xs text-gray-400 tabular-nums">
                    {{ item.fund_code }}
                  </div>
                </td>
                <td class="py-2 pr-3">
                  <div class="text-gray-800">
                    {{ item.sector_name ?? item.mapped_sector ?? '--' }}
                  </div>
                  <div class="text-xs text-gray-400">
                    {{ item.mapping_status }}
                  </div>
                </td>
                <td class="py-2 pr-3">
                  <span
                    class="inline-flex px-2 py-0.5 rounded text-xs font-medium"
                    :class="badgeClass(item)"
                  >
                    {{ statusText(item) }}
                  </span>
                </td>
                <td class="py-2 pr-3 text-right tabular-nums" :class="valueColor(item.first_half_sum_yi)">
                  {{ fmtYi(item.first_half_sum_yi) }}
                </td>
                <td class="py-2 pr-3 text-right tabular-nums" :class="valueColor(item.second_half_sum_yi)">
                  {{ fmtYi(item.second_half_sum_yi) }}
                </td>
                <td class="py-2 pr-3 text-right font-semibold tabular-nums" :class="valueColor(item.delta_yi)">
                  {{ fmtYi(item.delta_yi) }}
                </td>
                <td class="py-2 text-right text-gray-500 tabular-nums">
                  {{ item.sample_days }}/{{ data.window }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </section>
</template>
