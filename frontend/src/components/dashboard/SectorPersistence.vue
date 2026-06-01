<script setup lang="ts">
import type { SectorPersistenceItem, SectorPersistenceResponse } from '../../types'
import StaleBanner from './StaleBanner.vue'

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

// PR21:第三行窗口统计(5/10/20 日)。
// spec:
//   今日 inflow > 0  → 优先显示"流入X / Top20 Y"
//   今日 outflow < 0 → 优先显示"流出X / Top20 Y"
//   今日 = 0 (持平) → 同时显示"流入X / 流出Y / Top20 Z"
// 一行三段(5/10/20 日各一段)用 · 分隔;长了 flex wrap 自适应。
type WindowDirection = 'inflow' | 'outflow' | 'neutral'

function directionForItem(item: SectorPersistenceItem): WindowDirection {
  const n = Number(item.main_inflow_yi)
  if (n > 0) return 'inflow'
  if (n < 0) return 'outflow'
  return 'neutral'
}

interface WindowSegment {
  label: string       // "近5日"
  inflow: number
  outflow: number
  top20: number
}

function windowSegments(item: SectorPersistenceItem): WindowSegment[] {
  return [
    {
      label: '近5日',
      inflow: item.last_5_inflow_days,
      outflow: item.last_5_outflow_days,
      top20: item.last_5_top20_days,
    },
    {
      label: '近10日',
      inflow: item.last_10_inflow_days,
      outflow: item.last_10_outflow_days,
      top20: item.last_10_top20_days,
    },
    {
      label: '近20日',
      inflow: item.last_20_inflow_days,
      outflow: item.last_20_outflow_days,
      top20: item.last_20_top20_days,
    },
  ]
}

function segmentText(seg: WindowSegment, dir: WindowDirection): string {
  // 简化字符串:流入X 或 流出X 或 流入X/流出Y
  if (dir === 'inflow') {
    return `${seg.label} 流入${seg.inflow} / Top20 ${seg.top20}`
  }
  if (dir === 'outflow') {
    return `${seg.label} 流出${seg.outflow} / Top20 ${seg.top20}`
  }
  // neutral:同时显示双向
  return `${seg.label} 流入${seg.inflow}/流出${seg.outflow} / Top20 ${seg.top20}`
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
      <StaleBanner :freshness="data?.freshness" />
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

              <!-- 第 2 行:连续 inflow/outflow + 连续 Top20 -->
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
              </div>

              <!-- 第 3 行(PR21):5/10/20 日窗口统计 -->
              <div
                class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-gray-500 tabular-nums mt-1 pl-9"
              >
                <template
                  v-for="(seg, idx) in windowSegments(item)"
                  :key="seg.label"
                >
                  <span
                    v-if="idx > 0"
                    class="text-gray-300"
                  >·</span>
                  <span>{{ segmentText(seg, directionForItem(item)) }}</span>
                </template>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
