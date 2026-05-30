<script setup lang="ts">
import type { TopFunds as TopFundsData } from '../../types'

// Top 20 基金卡(Phase 5.1 PR9)。
//
// 字段密度比 TopSectors 高(基金有 score + matched_sectors + reason),
// 每行 4 块视觉信息:
//   - 第 1 块:rank(左极窄)
//   - 第 2 块:fund_name + score 徽章(右上角)
//   - 第 3 块:matched_sectors chips(每个板块一个小药丸)
//   - 第 4 块:main_inflow_wan + change_pct(一行,两端对齐)
//   - 第 5 块:reason(灰色小字,line-clamp-1 避免撑爆)
//
// score chip 三档色:8-9 强(emerald)/ 6-7 普通(blue)/ <6 弱(gray)。
// matched_sectors 灰底 chip。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: TopFundsData | null
  error: string
}>()

function fmtYi(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'n/a'
  const yi = Number(wanStr) / 10_000
  const sign = yi > 0 ? '+' : ''
  return `${sign}${yi.toFixed(1)}亿`
}

function fmtPct(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'n/a'
  const n = Number(decStr) * 100
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function inflowColor(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'text-gray-500'
  const n = Number(wanStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function pctColor(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'text-gray-500'
  const n = Number(decStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function scoreChipClass(score: number): string {
  // 持续性 0-9。8-9 强,6-7 普通,<6 弱;颜色梯度
  if (score >= 8) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (score >= 6) return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-gray-100 text-gray-500 border-gray-200'
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="flex items-center justify-between px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-purple-500 rounded-sm"></span>
        Top 20 基金
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
        <p v-if="data.funds.length === 0" class="text-gray-400 text-sm">
          暂无数据(基金需有 sector_aliases 映射 + 当日 sector_flow 数据)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ data.funds.length }} 条 · 按 via_sector 主力净流入降序
          </p>
          <ul class="divide-y divide-gray-100">
            <li v-for="f in data.funds" :key="f.fund_code" class="py-3">
              <div class="flex items-start gap-2">
                <span
                  class="text-xs text-gray-400 tabular-nums w-7 text-right shrink-0 pt-1"
                >
                  #{{ f.rank }}
                </span>
                <div class="flex-1 min-w-0">
                  <!-- 行 1:fund_name + score chip 右贴齐 -->
                  <div class="flex items-start justify-between gap-2">
                    <div class="text-sm text-gray-800 font-medium truncate flex-1">
                      {{ f.fund_name }}
                    </div>
                    <span
                      class="text-xs px-1.5 py-0.5 rounded border tabular-nums whitespace-nowrap shrink-0"
                      :class="scoreChipClass(f.score)"
                      title="SignalEngine 持续性总分(基础 0-4 + 连续 0-3 + 量价 0-2)"
                    >
                      {{ f.score }}/9
                    </span>
                  </div>

                  <!-- 行 2:matched_sectors chips -->
                  <div
                    v-if="f.matched_sectors.length > 0"
                    class="flex flex-wrap gap-1 mt-1.5"
                  >
                    <span
                      v-for="m in f.matched_sectors"
                      :key="m.sector_code"
                      class="text-[11px] leading-none px-1.5 py-1 rounded bg-gray-100 text-gray-600"
                    >
                      {{ m.sector_name }}
                    </span>
                  </div>

                  <!-- 行 3:main_inflow + change_pct -->
                  <div
                    class="flex items-center justify-between mt-1.5 text-xs tabular-nums"
                  >
                    <span
                      class="font-semibold"
                      :class="inflowColor(f.main_inflow_wan)"
                    >
                      {{ fmtYi(f.main_inflow_wan) }}
                    </span>
                    <span class="text-gray-500">
                      涨跌
                      <span :class="pctColor(f.change_pct)">
                        {{ fmtPct(f.change_pct) }}
                      </span>
                    </span>
                  </div>

                  <!-- 行 4:reason 灰小字 -->
                  <p
                    class="text-[11px] text-gray-400 mt-1 line-clamp-1"
                    :title="f.reason"
                  >
                    {{ f.reason }}
                  </p>
                </div>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
