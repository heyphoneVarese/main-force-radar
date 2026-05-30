<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import type { HoldingSignal, HoldingsSummary } from '../../types'

// 我的持仓明细卡(Phase 5.1 PR10)。
//
// 响应式策略:跟 Holdings.vue 同款 useMediaQuery 768px 分界 —
//   < 768px → 卡片堆叠
//   ≥ 768px → 表格
// 渲染分支只走一边,DOM 节点不翻倍。
//
// 顶部加 signal_type 计数横条:42 只持仓滚动前先给鸟瞰图。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: HoldingsSummary | null
  error: string
}>()

const isMobile = useMediaQuery('(max-width: 768px)')

// ===== signal_type → 视觉 =====
// R3.1 红线:5 个状态词都是情绪描述,绝不出现 buy/sell/long/short/hold。

function signalPillClass(sig: string): string {
  // 配色:bullish 红强 / bearish 绿弱 / warning 橙 / neutral 灰 / N/A 淡灰
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

function scoreChipClass(score: number): string {
  // 跟 TopFunds 同口径:8-9 emerald 强 / 6-7 blue 普通 / <6 gray 弱
  if (score >= 8) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (score >= 6) return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-gray-100 text-gray-500 border-gray-200'
}

function signalCounts(holdings: HoldingSignal[]): Array<[string, number]> {
  const counts: Record<string, number> = {}
  for (const h of holdings) {
    counts[h.signal_type] = (counts[h.signal_type] || 0) + 1
  }
  const order = ['bullish', 'warning', 'neutral', 'bearish', 'not_applicable']
  return order
    .filter((k) => k in counts)
    .map((k) => [k, counts[k]] as [string, number])
}

// ===== 金额/百分数格式化 =====

function fmtYi(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return '—'
  const yi = Number(wanStr) / 10_000
  const sign = yi > 0 ? '+' : ''
  return `${sign}${yi.toFixed(1)}亿`
}

function fmtPct(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return '—'
  const n = Number(decStr) * 100
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function inflowColor(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'text-gray-400'
  const n = Number(wanStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function pctColor(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'text-gray-400'
  const n = Number(decStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="flex items-center justify-between px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-teal-500 rounded-sm"></span>
        我的持仓分析
      </h3>
      <span
        v-if="status === 'ready' && data?.trade_date"
        class="text-xs text-gray-400 tabular-nums"
      >
        截至 {{ data.trade_date }}
      </span>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.holdings.length === 0" class="text-gray-400 text-sm">
          暂无持仓(去 Holdings 页添加)
        </p>
        <template v-else>
          <!-- 鸟瞰:signal_type 计数 -->
          <div
            class="flex flex-wrap items-center gap-2 mb-3 text-xs text-gray-500"
          >
            <span class="tabular-nums">
              共 {{ data.holdings.length }} 只 ·
            </span>
            <span
              v-for="[sig, count] in signalCounts(data.holdings)"
              :key="sig"
              class="px-1.5 py-0.5 rounded border tabular-nums"
              :class="signalPillClass(sig)"
            >
              {{ sig }} {{ count }}
            </span>
          </div>

          <!-- 移动端:卡片堆叠 -->
          <div v-if="isMobile" class="space-y-2">
            <div
              v-for="h in data.holdings"
              :key="h.fund_code"
              class="border rounded-md p-3 space-y-2"
            >
              <!-- 行 1:名 + 信号 chip -->
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0 flex-1">
                  <div class="text-sm text-gray-900 font-medium truncate">
                    {{ h.fund_name || h.fund_code }}
                  </div>
                  <div class="text-xs text-gray-400 tabular-nums">
                    {{ h.fund_code }}
                  </div>
                </div>
                <span
                  class="text-xs px-2 py-0.5 rounded border whitespace-nowrap shrink-0"
                  :class="signalPillClass(h.signal_type)"
                >
                  {{ h.signal_type }}
                </span>
              </div>

              <!-- 行 2:related_sectors chips -->
              <div
                v-if="h.related_sectors.length > 0"
                class="flex flex-wrap gap-1"
              >
                <span
                  v-for="s in h.related_sectors"
                  :key="s"
                  class="text-[10px] leading-none px-1.5 py-1 rounded bg-gray-100 text-gray-500"
                >
                  {{ s }}
                </span>
              </div>

              <!-- 行 3:score + via_sector + inflow + change_pct -->
              <div class="flex items-center justify-between text-xs">
                <div class="flex items-center gap-2 flex-wrap">
                  <span
                    class="px-1.5 py-0.5 rounded border tabular-nums"
                    :class="scoreChipClass(h.persistence_score)"
                  >
                    {{ h.persistence_score }}/9
                  </span>
                  <span class="text-gray-500 tabular-nums">
                    via {{ h.via_sector ?? '—' }}
                  </span>
                </div>
                <div class="text-right">
                  <div
                    class="font-medium tabular-nums"
                    :class="inflowColor(h.main_inflow_wan)"
                  >
                    {{ fmtYi(h.main_inflow_wan) }}
                  </div>
                  <div
                    class="text-[11px] tabular-nums"
                    :class="pctColor(h.change_pct)"
                  >
                    {{ fmtPct(h.change_pct) }}
                  </div>
                </div>
              </div>

              <!-- 行 4:reason -->
              <p
                class="text-[11px] text-gray-400 line-clamp-2"
                :title="h.reason"
              >
                {{ h.reason }}
              </p>
            </div>
          </div>

          <!-- 桌面:表格 -->
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr
                  class="text-xs text-gray-500 border-b text-left font-medium"
                >
                  <th class="py-2 pr-3">基金</th>
                  <th class="py-2 px-2 whitespace-nowrap">信号</th>
                  <th class="py-2 px-2 whitespace-nowrap">持续性</th>
                  <th class="py-2 px-2 whitespace-nowrap">via</th>
                  <th class="py-2 px-2 text-right whitespace-nowrap">主力净流入</th>
                  <th class="py-2 px-2 text-right whitespace-nowrap">涨跌</th>
                  <th class="py-2 pl-2">说明</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="h in data.holdings"
                  :key="h.fund_code"
                  class="border-b last:border-b-0 hover:bg-gray-50/50"
                >
                  <td class="py-2.5 pr-3 max-w-xs">
                    <div class="text-gray-900 font-medium truncate">
                      {{ h.fund_name || h.fund_code }}
                    </div>
                    <div class="flex items-center gap-1.5 mt-0.5">
                      <span class="text-xs text-gray-400 tabular-nums">
                        {{ h.fund_code }}
                      </span>
                      <span
                        v-for="s in h.related_sectors"
                        :key="s"
                        class="text-[10px] leading-none px-1 py-0.5 rounded bg-gray-100 text-gray-500"
                      >
                        {{ s }}
                      </span>
                    </div>
                  </td>
                  <td class="px-2 whitespace-nowrap">
                    <span
                      class="text-xs px-2 py-0.5 rounded border"
                      :class="signalPillClass(h.signal_type)"
                    >
                      {{ h.signal_type }}
                    </span>
                  </td>
                  <td class="px-2 whitespace-nowrap">
                    <span
                      class="text-xs px-1.5 py-0.5 rounded border tabular-nums"
                      :class="scoreChipClass(h.persistence_score)"
                    >
                      {{ h.persistence_score }}/9
                    </span>
                  </td>
                  <td
                    class="px-2 whitespace-nowrap text-xs text-gray-500 tabular-nums"
                  >
                    {{ h.via_sector ?? '—' }}
                  </td>
                  <td
                    class="px-2 text-right whitespace-nowrap tabular-nums font-medium"
                    :class="inflowColor(h.main_inflow_wan)"
                  >
                    {{ fmtYi(h.main_inflow_wan) }}
                  </td>
                  <td
                    class="px-2 text-right whitespace-nowrap text-xs tabular-nums"
                    :class="pctColor(h.change_pct)"
                  >
                    {{ fmtPct(h.change_pct) }}
                  </td>
                  <td class="pl-2 max-w-sm">
                    <p
                      class="text-xs text-gray-500 line-clamp-2"
                      :title="h.reason"
                    >
                      {{ h.reason }}
                    </p>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>
