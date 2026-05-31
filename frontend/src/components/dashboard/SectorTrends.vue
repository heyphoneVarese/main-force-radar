<script setup lang="ts">
import type {
  SectorTrendItem,
  SectorTrendsResponse,
} from '../../types'

// 20 天资金趋势(PR25)— 展示最近 20 个交易日主力净流入(亿元)
// 变化。纯事实可视化,不预测、不评分、不构成投资建议。
//
// R3 红线:
//  - 文案不出现 买入/卖出/加仓/减仓/推荐/建议/看多/看空/危险/机会/应该
//  - 标签如"流入/流出"是 A 股客观资金流向描述
//
// 数据源:GET /api/dashboard/sector-trends(后端复用 leaders + 历史
// sector_flow_daily;**不读** intraday)。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: SectorTrendsResponse | null
  error: string
}>()

function fmtYi(yi: string | null): string {
  if (yi === null) return 'n/a'
  const n = Number(yi)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function inflowColor(yi: string | null): string {
  if (yi === null) return 'text-gray-400'
  const n = Number(yi)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-600'
}

// 计算 sparkline 每个 bar 的高度百分比(基于 abs(value) / maxAbs)
// 返回数组(同 trend 长度),每项:
//   {value:number, posPct:number, negPct:number}
// posPct 用于 v>=0 的 bar(从中线向上),negPct 用于 v<0 的 bar(从中线向下)
interface BarMeta {
  value: number
  isPositive: boolean
  pct: number   // 0..50,作为容器高度的百分比(中线 → 顶/底之间最多 50%)
}

function barsFor(item: SectorTrendItem): BarMeta[] {
  const values = item.trend_20d.map((s) => Number(s))
  if (values.length === 0) return []
  const maxAbs = Math.max(...values.map((v) => Math.abs(v)), 0.0001)
  return values.map((v) => ({
    value: v,
    isPositive: v >= 0,
    // 用 absVal/maxAbs * 48 留出 2% 让"接近 0"的 bar 也可见(min 4%)
    pct: Math.max(4, (Math.abs(v) / maxAbs) * 48),
  }))
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span class="inline-block w-1.5 h-4 bg-sky-500 rounded-sm"></span>
          资金趋势 · 最近20日
        </h3>
        <span
          v-if="status === 'ready' && data?.trade_date"
          class="text-xs text-gray-400 tabular-nums"
        >
          截至 {{ data.trade_date }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-1">
        展示最近20个交易日主力净流入变化
      </p>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.items.length === 0" class="text-gray-400 text-sm">
          暂无趋势数据
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ data.items.length }} 条 · 顺序跟连续Top20榜一致
          </p>
          <ul class="space-y-3">
            <li
              v-for="(item, idx) in data.items"
              :key="item.sector_code"
              class="rounded-md border border-gray-100 bg-gray-50/40 p-3"
            >
              <!-- 第 1 行:#rank + name + 最新 inflow -->
              <div class="flex items-center justify-between gap-3 flex-wrap">
                <div class="flex items-center gap-2 min-w-0">
                  <span
                    class="text-xs text-gray-400 tabular-nums w-6 text-right shrink-0"
                  >
                    #{{ idx + 1 }}
                  </span>
                  <span class="text-sm font-semibold text-gray-800 truncate">
                    {{ item.sector_name }}
                  </span>
                </div>
                <span
                  class="text-sm font-semibold whitespace-nowrap tabular-nums"
                  :class="inflowColor(item.latest_main_inflow_yi)"
                >
                  最新 {{ fmtYi(item.latest_main_inflow_yi) }}
                </span>
              </div>

              <!-- 第 2 行:事实串 -->
              <div
                class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-gray-600 mt-1.5 pl-8"
              >
                <span>连续Top20 {{ item.continuous_top20_days }} 天</span>
                <span class="text-gray-300">·</span>
                <span>近20 流入 {{ item.last_20_inflow_days }} 天</span>
                <span class="text-gray-300">·</span>
                <span class="text-gray-400">共 {{ item.trend_20d.length }} 个数据点</span>
              </div>

              <!-- 第 3 行:sparkline 纯 CSS,中线 0 →上红下绿 -->
              <div
                v-if="item.trend_20d.length > 0"
                class="mt-2 ml-8 relative h-12 flex items-stretch gap-px"
                role="img"
                :aria-label="`${item.sector_name} 近${item.trend_20d.length}日主力净流入趋势`"
              >
                <!-- 中线 -->
                <div
                  class="absolute left-0 right-0 top-1/2 h-px bg-gray-300 pointer-events-none"
                ></div>
                <!-- 每个 bar -->
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

              <!-- 时间提示 -->
              <div
                v-if="item.trend_20d.length > 1"
                class="flex justify-between text-[10px] text-gray-400 mt-1 ml-8"
              >
                <span>← {{ item.trend_20d.length }} 天前</span>
                <span>最新 →</span>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
