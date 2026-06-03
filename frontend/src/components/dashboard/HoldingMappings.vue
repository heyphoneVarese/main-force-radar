<script setup lang="ts">
import { computed } from 'vue'
import type { TopFund, TopFunds } from '../../types'

// 我的持仓映射卡(Phase 5.1 PR11)。
//
// 语义修正:这不是 "Top 20 基金"(那暗示市场维度排行)。它真正在做的是:
// "我的持仓基金,按其映射板块的主力资金流入强度排序"。
//
// 数据流:
//   funds/top 后端返回所有有数据的 funds (52)。本组件用 holdingCodes
//   prop 在前端过滤,只留持仓基金(~51)。这样 backend 端点不动,
//   语义靠 UI 表达。
//
// 字段策略:
//   显示 — fund_name / 持仓 badge / 板块 #rank / via_sector_name /
//          net_inflow / score chip
//   移除 — change_pct(其实是板块的涨跌幅,不是基金的,放基金行旁边
//          会误导;且多个基金共享同一板块时会重复同一数字 →
//          "duplicated board percentage data")
//   移除 — matched_sectors chip 列表(信息已被 via_sector 行包含)
//   移除 — reason(信息已被 score chip + net inflow 覆盖)
//
// 板块 rank 来源:Dashboard.vue 用 sectors/top?sector_type=all&n=100
// 单独拉一次,建 code→rank 映射传进来。via_sector 直接使用后端显式字段。

const props = defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: TopFunds | null
  error: string
  holdingCodes: Set<string>
  sectorRankByCode: Map<string, number>
}>()

const filteredFunds = computed<TopFund[]>(() => {
  if (!props.data?.funds) return []
  return props.data.funds.filter((f) => props.holdingCodes.has(f.fund_code))
})

function viaSector(f: TopFund): {
  code: string
  name: string
  rank: number | null
} {
  const rank = props.sectorRankByCode.get(f.via_sector_code) ?? null
  return {
    code: f.via_sector_code,
    name: f.via_sector_name,
    rank,
  }
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
          <span class="inline-block w-1.5 h-4 bg-purple-500 rounded-sm"></span>
          我的持仓映射
        </h3>
        <span
          v-if="status === 'ready' && data?.trade_date"
          class="text-xs text-gray-400 tabular-nums"
        >
          截至 {{ data.trade_date }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-1">
        根据主力资金流入板块排序 · 仅含我的持仓
      </p>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="filteredFunds.length === 0" class="text-gray-400 text-sm">
          暂无持仓映射(持仓基金的映射板块当日无数据,或 holdings 未加载)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ filteredFunds.length }} 只持仓基金
          </p>
          <ul class="divide-y divide-gray-100">
            <li v-for="f in filteredFunds" :key="f.fund_code" class="py-3">
              <div class="flex items-start gap-3">
                <!-- 板块 rank 前缀 -->
                <span
                  class="text-xs text-gray-400 tabular-nums shrink-0 pt-1 w-14 text-right"
                  :title="viaSector(f).code"
                >
                  <template v-if="viaSector(f).rank">
                    板块 #{{ viaSector(f).rank }}
                  </template>
                  <template v-else>—</template>
                </span>

                <div class="flex-1 min-w-0">
                  <!-- 行 1:fund_name + 持仓 badge + score chip 右贴齐 -->
                  <div class="flex items-start justify-between gap-2">
                    <div class="flex items-center gap-1.5 min-w-0">
                      <div class="text-sm text-gray-800 font-medium truncate">
                        {{ f.fund_name }}
                      </div>
                      <span
                        class="text-[10px] leading-none px-1.5 py-1 rounded bg-teal-50 text-teal-700 border border-teal-200 shrink-0"
                      >
                        持仓
                      </span>
                    </div>
                    <span
                      class="text-xs px-1.5 py-0.5 rounded border tabular-nums whitespace-nowrap shrink-0"
                      :class="scoreChipClass(f.score)"
                      title="SignalEngine 持续性总分(基础 0-4 + 连续 0-3 + 量价 0-2)"
                    >
                      {{ f.score }}/9
                    </span>
                  </div>

                  <!-- 行 2:via_sector 名(全局 rank 最强的那个 mapped 板块)-->
                  <div class="text-xs text-gray-500 mt-1">
                    via
                    <span class="text-gray-700 font-medium">
                      {{ viaSector(f).name }}
                    </span>
                  </div>

                  <!-- 行 3:主力净流入(无 change_pct,该值属于板块而非基金)-->
                  <div
                    class="text-sm font-semibold mt-1 tabular-nums"
                    :class="inflowColor(f.main_inflow_wan)"
                  >
                    {{ fmtYi(f.main_inflow_wan) }}
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
