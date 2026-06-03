<script setup lang="ts">
import type { TopFunds } from '../../types'

// 主线关联基金候选(Phase 5.1 PR12)。
//
// 跟 HoldingMappings 的区别(关键!):
//   - 数据源都是 GET /api/dashboard/funds/top(默认 n=20)
//   - HoldingMappings:客户端过滤 → 仅显示我的持仓(语义="我持仓中谁踩中强势板块")
//   - MarketTopFunds(本组件):不过滤 → 显示候选池 Top 20 全(语义="市场上哪些基金踩中强势板块")
//
// 不要被名字误导:
//   "最强 20 基金候选" ≠ "市场最强 20 基金涨幅排名"。
//   排序键是 "基金所映射板块的主力净流入",不是基金本身的净值涨幅。
//   change_pct 字段属于板块,不是基金 — 本组件**故意不显示**它。
//
const props = defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: TopFunds | null
  error: string
  holdingCodes: Set<string>
}>()

function isHeld(code: string): boolean {
  return props.holdingCodes.has(code)
}

function fmtYi(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'n/a'
  const yi = Number(wanStr) / 10_000
  const sign = yi > 0 ? '+' : ''
  return `${sign}${yi.toFixed(1)}亿`
}

function inflowColor(wanStr: string | null | undefined): string {
  if (wanStr === null || wanStr === undefined) return 'text-gray-500'
  const n = Number(wanStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function scoreChipClass(score: number): string {
  if (score >= 8) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (score >= 6) return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-gray-100 text-gray-500 border-gray-200'
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span class="inline-block w-1.5 h-4 bg-amber-500 rounded-sm"></span>
          主线关联基金候选
        </h3>
        <span
          v-if="status === 'ready' && data?.trade_date"
          class="text-xs text-gray-400 tabular-nums"
        >
          截至 {{ data.trade_date }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-1">
        按高置信主题映射与板块资金排序，非基金净值涨幅排名
      </p>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.funds.length === 0" class="text-gray-400 text-sm">
          暂无数据(候选池基金的板块当日无数据)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ data.funds.length }} 只候选 · 来源 funds 表全部
          </p>
          <ul class="divide-y divide-gray-100">
            <li v-for="f in data.funds" :key="f.fund_code" class="py-3">
              <div class="flex items-start gap-3">
                <!-- rank 前缀 -->
                <span
                  class="text-xs text-gray-400 tabular-nums shrink-0 pt-1 w-8 text-right"
                >
                  #{{ f.rank }}
                </span>

                <div class="flex-1 min-w-0">
                  <!-- 行 1:fund_name + 持有状态 badge + score chip -->
                  <div class="flex items-start justify-between gap-2">
                    <div class="text-sm text-gray-800 font-medium truncate flex-1">
                      {{ f.fund_name }}
                    </div>
                    <div class="flex items-center gap-1.5 shrink-0">
                      <span
                        class="text-[10px] leading-none px-1.5 py-1 rounded border whitespace-nowrap"
                        :class="
                          isHeld(f.fund_code)
                            ? 'bg-teal-50 text-teal-700 border-teal-200'
                            : 'bg-amber-50 text-amber-700 border-amber-200'
                        "
                      >
                        {{ isHeld(f.fund_code) ? '已持有' : '候选' }}
                      </span>
                      <span
                        class="text-xs px-1.5 py-0.5 rounded border tabular-nums whitespace-nowrap"
                        :class="scoreChipClass(f.score)"
                        title="SignalEngine 持续性总分(基础 0-4 + 连续 0-3 + 量价 0-2)"
                      >
                        {{ f.score }}/9
                      </span>
                    </div>
                  </div>

                  <!-- 行 2:fund_code · via sector -->
                  <div class="text-xs text-gray-500 mt-1">
                    <span class="tabular-nums">{{ f.fund_code }}</span>
                    <span class="text-gray-300 mx-1.5">·</span>
                    via
                    <span class="text-gray-700 font-medium">
                      {{ f.via_sector_name }}
                    </span>
                  </div>

                  <!-- 行 3:主力净流入(无 change_pct)-->
                  <div
                    class="text-sm font-semibold mt-1 tabular-nums"
                    :class="inflowColor(f.main_inflow_wan)"
                  >
                    主力净流入 {{ fmtYi(f.main_inflow_wan) }}
                  </div>
                </div>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
