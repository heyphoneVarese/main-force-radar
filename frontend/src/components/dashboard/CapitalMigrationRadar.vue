<script setup lang="ts">
import type {
  CapitalMigrationResponse,
  CapitalMigrationSectorItem,
} from '../../types'
import DataTimeBadge from './DataTimeBadge.vue'
import StaleBanner from './StaleBanner.vue'

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: CapitalMigrationResponse | null
  error: string
}>()

function fmtYi(v: string | null | undefined): string {
  if (v === null || v === undefined) return '--'
  const n = Number(v)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function valueColor(v: string | null | undefined): string {
  if (v === null || v === undefined) return 'text-gray-500'
  const n = Number(v)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function statusText(item: CapitalMigrationSectorItem): string {
  if (item.migration_status === 'weak_to_strong') return '弱转强'
  if (item.migration_status === 'strong_to_weak') return '强转弱'
  if (item.migration_status === 'outflowing') return '持续流出'
  return '持续流入'
}

const groups: Array<{
  key: keyof Pick<
    CapitalMigrationResponse,
    'inflowing' | 'outflowing' | 'weak_to_strong' | 'strong_to_weak'
  >
  title: string
}> = [
  { key: 'inflowing', title: '持续流入' },
  { key: 'outflowing', title: '持续流出' },
  { key: 'weak_to_strong', title: '弱转强' },
  { key: 'strong_to_weak', title: '强转弱' },
]
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-cyan-500 rounded-sm"></span>
        资金迁移雷达
      </h3>
      <DataTimeBadge
        v-if="status === 'ready'"
        class="mt-1"
        :time-meta="data?.time_meta"
        :freshness="data?.freshness"
      />
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
        <div class="text-xs text-gray-500 mb-3">
          样本 {{ data.sample_days }}/{{ data.window }} 个交易日
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-4 gap-3">
          <div
            v-for="group in groups"
            :key="group.key"
            class="border rounded-lg overflow-hidden"
          >
            <div class="px-3 py-2 bg-gray-50 text-sm font-semibold text-gray-800">
              {{ group.title }}
            </div>
            <div v-if="data[group.key].length === 0" class="p-3 text-sm text-gray-400">
              暂无数据
            </div>
            <ul v-else class="divide-y divide-gray-100">
              <li
                v-for="item in data[group.key]"
                :key="`${group.key}-${item.sector_code}`"
                class="p-3"
              >
                <div class="flex items-center justify-between gap-2">
                  <div class="min-w-0">
                    <div class="text-sm font-medium text-gray-900 truncate">
                      {{ item.sector_name }}
                    </div>
                    <div class="text-[11px] text-gray-400 tabular-nums">
                      {{ statusText(item) }} · 样本 {{ item.sample_days }} 日
                    </div>
                  </div>
                  <div
                    class="text-sm font-semibold tabular-nums shrink-0"
                    :class="valueColor(item.delta_yi)"
                  >
                    {{ fmtYi(item.delta_yi) }}
                  </div>
                </div>
                <div class="mt-2 grid grid-cols-2 gap-2 text-[11px] tabular-nums">
                  <span class="text-gray-500">前半 {{ fmtYi(item.first_half_sum_yi) }}</span>
                  <span class="text-gray-500">后半 {{ fmtYi(item.second_half_sum_yi) }}</span>
                  <span class="text-gray-500">流入 {{ item.inflow_days_20 }} 日</span>
                  <span class="text-gray-500">流出 {{ item.outflow_days_20 }} 日</span>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>
