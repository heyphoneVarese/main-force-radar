<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import type { HoldingFactItem, HoldingFactsSummary } from '../../types'
import StaleBanner from './StaleBanner.vue'

// 我的持仓分析(PR26 重构)— 取代情绪系统(bullish/bearish/warning/
// neutral)。卡片只显示客观事实:
//   每只持仓 → mapped_sector + 连续Top20天数 + 近20日Top20/流入次数 +
//             最新收盘净流入 + 盘中净流入(如果存在)
//   顶部 buckets → 按 continuous_top20_days 分四档计数
//
// R3 红线:
//  - **不出现** bullish / bearish / warning / neutral / signal_type /
//    persistence_score / score / health / rating / 任何情绪词
//  - 不出现 买入 / 卖出 / 加仓 / 减仓 / 推荐 / 建议 / 看多 / 看空 /
//    危险 / 机会 / 应该
//  - 红/绿配色只用于"资金流向"(A 股惯例:红 +,绿 -),不携带评价语义

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: HoldingFactsSummary | null
  error: string
}>()

const isMobile = useMediaQuery('(max-width: 768px)')

// ===== 格式化 =====

function fmtYi(yi: string | null | undefined): string {
  if (yi === null || yi === undefined) return '—'
  const n = Number(yi)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function fmtPctFraction(decStr: string | null | undefined): string {
  // change_pct 是小数(0.0234 = 2.34%)
  if (decStr === null || decStr === undefined) return '—'
  const n = Number(decStr) * 100
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function fmtPctPercent(decStr: string | null | undefined): string {
  // intraday_change_pct 是百分数(-6.40 = -6.40%)
  if (decStr === null || decStr === undefined) return '—'
  const n = Number(decStr)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function inflowColor(s: string | null | undefined): string {
  if (s === null || s === undefined) return 'text-gray-400'
  const n = Number(s)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function pctColorFraction(s: string | null | undefined): string {
  if (s === null || s === undefined) return 'text-gray-400'
  const n = Number(s)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

// related_sectors chip 截断:超过 3 个显示 +N
function visibleSectorChips(item: HoldingFactItem): string[] {
  return item.related_sectors.slice(0, 3)
}
function extraSectorCount(item: HoldingFactItem): number {
  return Math.max(0, item.related_sectors.length - 3)
}

function mappingStatusLabel(item: HoldingFactItem): string {
  if (item.mapping_status === 'low_confidence') return '待确认'
  if (item.mapping_status === 'not_applicable') return '不适用'
  return '未映射'
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
      <StaleBanner :freshness="data?.freshness" />
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.holdings.length === 0" class="text-gray-400 text-sm">
          暂无持仓(去 Holdings 页添加)
        </p>
        <template v-else>
          <!-- 顶部:事实 buckets(取代情绪计数)-->
          <div
            class="flex flex-wrap items-center gap-2 mb-3 text-xs text-gray-600"
          >
            <span class="tabular-nums">
              共 {{ data.buckets.total }} 只 ·
            </span>
            <span
              class="px-1.5 py-0.5 rounded border tabular-nums bg-purple-50 text-purple-700 border-purple-200"
            >
              连续Top20 ≥20天 {{ data.buckets.persistence_ge_20 }}
            </span>
            <span
              class="px-1.5 py-0.5 rounded border tabular-nums bg-indigo-50 text-indigo-700 border-indigo-200"
            >
              连续Top20 5~19天 {{ data.buckets.persistence_5_to_19 }}
            </span>
            <span
              class="px-1.5 py-0.5 rounded border tabular-nums bg-gray-100 text-gray-600 border-gray-200"
            >
              连续Top20 &lt;5天 {{ data.buckets.persistence_lt_5 }}
            </span>
            <span
              class="px-1.5 py-0.5 rounded border tabular-nums bg-gray-50 text-gray-400 border-gray-100"
            >
              未映射 {{ data.buckets.unmapped }}
            </span>
          </div>

          <!-- 移动端:卡片堆叠 -->
          <div v-if="isMobile" class="space-y-2">
            <div
              v-for="h in data.holdings"
              :key="h.fund_code"
              class="border rounded-md p-3 space-y-2"
            >
              <!-- 行 1:fund 名 + code -->
              <div class="min-w-0">
                <div class="text-sm text-gray-900 font-medium truncate">
                  {{ h.fund_name || h.fund_code }}
                </div>
                <div class="text-xs text-gray-400 tabular-nums">
                  {{ h.fund_code }}
                </div>
              </div>

              <!-- 行 2:related_sectors chips + mapped_sector -->
              <div class="flex flex-wrap items-center gap-1 text-xs">
                <span
                  v-for="s in visibleSectorChips(h)"
                  :key="s"
                  class="text-[10px] leading-none px-1.5 py-1 rounded"
                  :class="
                    h.mapped_sector === s
                      ? 'bg-teal-50 text-teal-700 border border-teal-200'
                      : 'bg-gray-100 text-gray-500'
                  "
                >
                  {{ s }}
                </span>
                <span
                  v-if="extraSectorCount(h) > 0"
                  class="text-[10px] text-gray-400"
                >
                  +{{ extraSectorCount(h) }}
                </span>
                <span
                  v-if="h.mapped_sector === null"
                  class="text-[10px] text-gray-400 ml-auto"
                >
                  {{ mappingStatusLabel(h) }}
                </span>
              </div>

              <!-- 行 3:持续性事实(只在 mapped 时显示)-->
              <div
                v-if="h.mapped_sector !== null"
                class="grid grid-cols-3 gap-2 text-xs tabular-nums text-gray-600"
              >
                <div>
                  <div class="text-[10px] text-gray-400">连续Top20</div>
                  <div class="font-medium text-gray-800">
                    {{ h.continuous_top20_days }} 天
                  </div>
                </div>
                <div>
                  <div class="text-[10px] text-gray-400">近20日Top20</div>
                  <div class="font-medium text-gray-800">
                    {{ h.last_20_top20_days }} 次
                  </div>
                </div>
                <div>
                  <div class="text-[10px] text-gray-400">近20日流入</div>
                  <div class="font-medium text-gray-800">
                    {{ h.last_20_inflow_days }} 天
                  </div>
                </div>
              </div>

              <!-- 行 4:最新收盘 + 盘中 -->
              <div class="flex items-center justify-between text-xs">
                <div>
                  <div class="text-[10px] text-gray-400">最新收盘</div>
                  <div
                    class="text-sm font-medium tabular-nums"
                    :class="inflowColor(h.latest_main_inflow_yi)"
                  >
                    {{ fmtYi(h.latest_main_inflow_yi) }}
                  </div>
                  <div
                    class="text-[10px] tabular-nums"
                    :class="pctColorFraction(h.change_pct)"
                  >
                    {{ fmtPctFraction(h.change_pct) }}
                  </div>
                </div>
                <div class="text-right">
                  <div class="text-[10px] text-gray-400">盘中</div>
                  <template v-if="h.intraday_main_inflow_yi !== null">
                    <div
                      class="text-sm font-medium tabular-nums"
                      :class="inflowColor(h.intraday_main_inflow_yi)"
                    >
                      {{ fmtYi(h.intraday_main_inflow_yi) }}
                    </div>
                    <div
                      class="text-[10px] tabular-nums"
                      :class="pctColorFraction(h.intraday_change_pct)"
                    >
                      {{ fmtPctPercent(h.intraday_change_pct) }}
                    </div>
                  </template>
                  <div v-else class="text-xs text-gray-400">盘中暂无</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 桌面:表格 -->
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-xs text-gray-500 border-b text-left font-medium">
                  <th class="py-2 pr-3">基金</th>
                  <th class="py-2 px-2 whitespace-nowrap">映射板块</th>
                  <th class="py-2 px-2 text-right whitespace-nowrap">连续Top20</th>
                  <th class="py-2 px-2 text-right whitespace-nowrap">近20日Top20</th>
                  <th class="py-2 px-2 text-right whitespace-nowrap">近20日流入</th>
                  <th class="py-2 px-2 text-right whitespace-nowrap">最新收盘</th>
                  <th class="py-2 px-2 text-right whitespace-nowrap">涨跌</th>
                  <th class="py-2 pl-2 text-right whitespace-nowrap">盘中</th>
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
                        v-for="s in visibleSectorChips(h)"
                        :key="s"
                        class="text-[10px] leading-none px-1 py-0.5 rounded bg-gray-100 text-gray-500"
                      >
                        {{ s }}
                      </span>
                      <span
                        v-if="extraSectorCount(h) > 0"
                        class="text-[10px] text-gray-400"
                      >
                        +{{ extraSectorCount(h) }}
                      </span>
                    </div>
                  </td>
                  <td class="px-2 whitespace-nowrap">
                    <span
                      v-if="h.mapped_sector !== null"
                      class="text-xs px-2 py-0.5 rounded border bg-teal-50 text-teal-700 border-teal-200"
                    >
                      {{ h.mapped_sector }}
                    </span>
                    <span
                      v-else
                      class="text-xs text-gray-400 italic"
                    >
                      {{ mappingStatusLabel(h) }}
                    </span>
                  </td>
                  <td class="px-2 text-right whitespace-nowrap text-xs tabular-nums text-gray-700">
                    <template v-if="h.continuous_top20_days !== null">
                      {{ h.continuous_top20_days }} 天
                    </template>
                    <template v-else>—</template>
                  </td>
                  <td class="px-2 text-right whitespace-nowrap text-xs tabular-nums text-gray-700">
                    <template v-if="h.last_20_top20_days !== null">
                      {{ h.last_20_top20_days }} 次
                    </template>
                    <template v-else>—</template>
                  </td>
                  <td class="px-2 text-right whitespace-nowrap text-xs tabular-nums text-gray-700">
                    <template v-if="h.last_20_inflow_days !== null">
                      {{ h.last_20_inflow_days }} 天
                    </template>
                    <template v-else>—</template>
                  </td>
                  <td
                    class="px-2 text-right whitespace-nowrap tabular-nums font-medium"
                    :class="inflowColor(h.latest_main_inflow_yi)"
                  >
                    {{ fmtYi(h.latest_main_inflow_yi) }}
                  </td>
                  <td
                    class="px-2 text-right whitespace-nowrap text-xs tabular-nums"
                    :class="pctColorFraction(h.change_pct)"
                  >
                    {{ fmtPctFraction(h.change_pct) }}
                  </td>
                  <td
                    class="pl-2 text-right whitespace-nowrap tabular-nums"
                  >
                    <template v-if="h.intraday_main_inflow_yi !== null">
                      <div
                        class="font-medium"
                        :class="inflowColor(h.intraday_main_inflow_yi)"
                      >
                        {{ fmtYi(h.intraday_main_inflow_yi) }}
                      </div>
                      <div
                        class="text-[11px]"
                        :class="pctColorFraction(h.intraday_change_pct)"
                      >
                        {{ fmtPctPercent(h.intraday_change_pct) }}
                      </div>
                    </template>
                    <span v-else class="text-xs text-gray-400">盘中暂无</span>
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
