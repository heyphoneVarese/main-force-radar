<script setup lang="ts">
import type { SectorPersistenceItem, SectorPersistenceResponse } from '../../types'

// 主线连续性卡(PR20)— 板块在收盘数据上的连续天数事实。
//
// R3 红线:本组件渲染的全部是**客观计数事实**(continuous_*_days /
// last_20_*),不显示买卖建议、不预测涨跌、不出现 buy/sell/long/short/
// hold/加仓/减仓/继续持有/推荐 等词。
//
// 数据源:GET /api/dashboard/sectors/persistence(收盘 sector_flow_daily,
// 不读 intraday — spec 死命令避免盘中噪音污染历史连续性)。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: SectorPersistenceResponse | null
  error: string
}>()

function fmtYi(yi: string | null | undefined): string {
  if (yi === null || yi === undefined) return 'n/a'
  const n = Number(yi)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function inflowColor(yi: string | null | undefined): string {
  if (yi === null || yi === undefined) return 'text-gray-500'
  const n = Number(yi)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

// 连续流入 / 流出 / 中性 的文案 + 配色规则(spec)
function streakLabel(item: SectorPersistenceItem): {
  text: string
  cls: string
} {
  if (item.continuous_inflow_days > 0) {
    return {
      text: `连续流入 ${item.continuous_inflow_days} 天`,
      cls: 'text-red-600',
    }
  }
  if (item.continuous_outflow_days > 0) {
    return {
      text: `连续流出 ${item.continuous_outflow_days} 天`,
      cls: 'text-green-600',
    }
  }
  return { text: '今日中性 / 无连续', cls: 'text-gray-500' }
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span class="inline-block w-1.5 h-4 bg-indigo-500 rounded-sm"></span>
          主线连续性 · 收盘事实
        </h3>
        <span
          v-if="status === 'ready' && data?.trade_date"
          class="text-xs text-gray-400 tabular-nums"
        >
          截至 {{ data.trade_date }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-1">
        基于收盘数据,不含盘中噪音
      </p>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.items.length === 0" class="text-gray-400 text-sm">
          暂无收盘数据(等待 cron 15:20 采集完成)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ data.items.length }} 条
          </p>
          <ul class="divide-y divide-gray-100">
            <li v-for="item in data.items" :key="item.sector_code" class="py-2.5">
              <!-- 上行:rank + name + 今日 inflow -->
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-2 min-w-0">
                  <span
                    class="text-xs text-gray-400 tabular-nums w-7 text-right shrink-0"
                  >
                    #{{ item.rank }}
                  </span>
                  <span class="text-sm text-gray-800 font-medium truncate">
                    {{ item.sector_name }}
                  </span>
                </div>
                <span
                  class="text-sm font-semibold whitespace-nowrap tabular-nums"
                  :class="inflowColor(item.main_inflow_yi)"
                >
                  {{ fmtYi(item.main_inflow_yi) }}
                </span>
              </div>

              <!-- 下行:6 个事实字段(连续 inflow/outflow 二选一 + 连续 top20 + last 20)-->
              <div
                class="flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums mt-1 pl-9"
              >
                <span :class="streakLabel(item).cls">
                  {{ streakLabel(item).text }}
                </span>
                <span class="text-gray-300">·</span>
                <span class="text-gray-600">
                  连续Top20 {{ item.continuous_top20_days }} 天
                </span>
                <span class="text-gray-300">·</span>
                <span class="text-gray-500">
                  近20日Top20 {{ item.last_20_top20_days }} 次
                </span>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
