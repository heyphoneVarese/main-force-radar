<script setup lang="ts">
import { ref } from 'vue'
import type { SectorTrendItem, SectorTrendsResponse } from '../../types'
import StaleBanner from './StaleBanner.vue'

// 第 3 部分:板块详情(默认收起,点击展开 20 天 sparkline + 表格)。
//
// 数据源:/api/dashboard/sector-trends(每个板块带 trend_20d 亿元正序序列)。
// R3 红线:只显示历史观察值,无评分/预测/建议。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: SectorTrendsResponse | null
  error: string
}>()

// 二级展开:
//   level 1 (sparklineExpanded):点击行头 → 显示 sparkline
//   level 2 (tableExpanded):再点 "查看明细" → 显示 20 天表格
// 收起 sparkline 时同时收起 table。
const sparklineExpanded = ref<Set<string>>(new Set())
const tableExpanded = ref<Set<string>>(new Set())

function toggleSparkline(code: string) {
  const next = new Set(sparklineExpanded.value)
  if (next.has(code)) {
    next.delete(code)
    // 同时收掉 table
    const t = new Set(tableExpanded.value)
    t.delete(code)
    tableExpanded.value = t
  } else {
    next.add(code)
  }
  sparklineExpanded.value = next
}

function toggleTable(code: string) {
  const next = new Set(tableExpanded.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  tableExpanded.value = next
}

function fmtYi(yiStr: string): string {
  const n = Number(yiStr)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function inflowColor(yiStr: string | null | undefined): string {
  if (yiStr === null || yiStr === undefined) return 'text-gray-500'
  const n = Number(yiStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

// Sparkline:纯 CSS,中线 0 → 上红下绿,高度按 abs / maxAbs * 48%
interface BarMeta {
  value: number
  isPositive: boolean
  pct: number
}
function barsFor(item: SectorTrendItem): BarMeta[] {
  const values = item.trend_20d.map((s) => Number(s))
  if (values.length === 0) return []
  const maxAbs = Math.max(...values.map((v) => Math.abs(v)), 0.0001)
  return values.map((v) => ({
    value: v,
    isPositive: v >= 0,
    pct: Math.max(4, (Math.abs(v) / maxAbs) * 48),
  }))
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-sky-500 rounded-sm"></span>
        板块详情(20日资金历史)
      </h3>
      <p class="text-xs text-gray-500 mt-1">
        默认收起,点击展开查看该板块最近 20 天净流入序列
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
          暂无趋势数据
        </p>
        <ul v-else class="divide-y divide-gray-100">
          <li
            v-for="(item, idx) in data.items"
            :key="item.sector_code"
            class="py-2"
          >
            <button
              type="button"
              class="w-full flex items-center justify-between gap-3 text-left hover:bg-gray-50 rounded p-1.5 transition-colors"
              :aria-expanded="sparklineExpanded.has(item.sector_code)"
              @click="toggleSparkline(item.sector_code)"
            >
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-xs text-gray-400 tabular-nums w-6 text-right shrink-0">
                  #{{ idx + 1 }}
                </span>
                <span class="text-sm font-medium text-gray-800 truncate">
                  {{ item.sector_name }}
                </span>
                <span class="text-xs text-gray-400 tabular-nums">
                  连续Top20 {{ item.continuous_top20_days }} 天
                </span>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span
                  class="text-sm font-semibold tabular-nums"
                  :class="inflowColor(item.latest_main_inflow_yi)"
                >
                  {{ fmtYi(item.latest_main_inflow_yi) }}
                </span>
                <svg
                  class="w-3.5 h-3.5 text-gray-400 transition-transform"
                  :class="sparklineExpanded.has(item.sector_code) ? 'rotate-180' : ''"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    fill-rule="evenodd"
                    d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z"
                    clip-rule="evenodd"
                  />
                </svg>
              </div>
            </button>

            <!-- Level 1:sparkline -->
            <div
              v-if="sparklineExpanded.has(item.sector_code)"
              class="mt-2 pl-8 pr-2"
            >
              <div
                v-if="item.trend_20d.length > 0"
                class="relative h-12 flex items-stretch gap-px"
                role="img"
                :aria-label="`${item.sector_name} 最近 ${item.trend_20d.length} 天净流入序列`"
              >
                <div
                  class="absolute left-0 right-0 top-1/2 h-px bg-gray-300 pointer-events-none"
                ></div>
                <div
                  v-for="(bar, i) in barsFor(item)"
                  :key="i"
                  class="flex-1 relative"
                  :title="`第 ${i + 1} 天:${bar.value >= 0 ? '+' : ''}${bar.value.toFixed(1)}亿`"
                >
                  <div
                    v-if="bar.isPositive"
                    class="absolute left-0 right-0 bg-red-500 rounded-sm"
                    :style="{ bottom: '50%', height: `${bar.pct}%` }"
                  ></div>
                  <div
                    v-else
                    class="absolute left-0 right-0 bg-green-500 rounded-sm"
                    :style="{ top: '50%', height: `${bar.pct}%` }"
                  ></div>
                </div>
              </div>
              <div
                v-if="item.trend_20d.length > 1"
                class="flex justify-between text-[10px] text-gray-400 mt-1"
              >
                <span>← {{ item.trend_20d.length }} 天前</span>
                <span>最新 →</span>
              </div>

              <!-- Level 2 toggle:查看明细 -->
              <div class="mt-2">
                <button
                  type="button"
                  class="text-xs text-sky-600 hover:text-sky-800 inline-flex items-center gap-0.5 select-none"
                  :aria-expanded="tableExpanded.has(item.sector_code)"
                  @click="toggleTable(item.sector_code)"
                >
                  {{ tableExpanded.has(item.sector_code) ? '收起明细' : '查看明细' }}
                  <svg
                    class="w-3 h-3 transition-transform"
                    :class="tableExpanded.has(item.sector_code) ? 'rotate-180' : ''"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <path
                      fill-rule="evenodd"
                      d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </button>
              </div>

              <!-- Level 2:20 天数据表 -->
              <div
                v-if="tableExpanded.has(item.sector_code)"
                class="mt-2"
              >
                <h4 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  最近 {{ item.trend_20d.length }} 个交易日净流入(亿元)
                </h4>
                <div class="grid grid-cols-5 gap-x-3 gap-y-1 text-xs tabular-nums">
                  <span
                    v-for="(v, i) in item.trend_20d"
                    :key="i"
                    :class="inflowColor(v)"
                  >
                    {{ fmtYi(v) }}
                  </span>
                </div>
              </div>
            </div>
          </li>
        </ul>
      </template>
    </div>
  </section>
</template>
