<script setup lang="ts">
import type { DashboardRadarResponse } from '../../types'

// 主力雷达 — 盘中实时(PR16)。
//
// R3 红线:绝不渲染 buy/sell/long/short/hold/加仓/减仓/继续持有/建议
// 等操作指令词。score 是客观雷达分,文案只描述事实("强势板块"/
// "对应基金"/"主力净流入"等)。
//
// 数据形态:holdings + candidates 两个数组,各自已按 (score DESC,
// sector_rank ASC) 排好。每组独立渲染,空时友好提示。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: DashboardRadarResponse | null
  error: string
}>()

function fmtClock(iso: string | null): string {
  if (!iso) return ''
  return iso.slice(11, 16)
}

function fmtYi(yi: string | null | undefined): string {
  // 后端已经返回亿元 Decimal,前端直接显示
  if (yi === null || yi === undefined) return 'n/a'
  const n = Number(yi)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function fmtPct(pct: string | null | undefined): string {
  // 后端 sector_change_pct 已是百分数(2.10 = 2.10%),不需要 *100
  if (pct === null || pct === undefined) return 'n/a'
  const n = Number(pct)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function inflowColor(yi: string | null | undefined): string {
  if (yi === null || yi === undefined) return 'text-gray-500'
  const n = Number(yi)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function pctColor(pct: string | null | undefined): string {
  if (pct === null || pct === undefined) return 'text-gray-500'
  const n = Number(pct)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function scoreChipClass(score: number): string {
  // 8-9 强 emerald / 6-7 普通 blue / <6 弱 gray(跟其它卡同口径)
  if (score >= 8) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (score >= 6) return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-gray-100 text-gray-500 border-gray-200'
}

function badgeClass(badge: string): string {
  return badge === '已持有'
    ? 'bg-teal-50 text-teal-700 border-teal-200'
    : 'bg-amber-50 text-amber-700 border-amber-200'
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span class="inline-block w-1.5 h-4 bg-rose-500 rounded-sm"></span>
          主力雷达 · 盘中实时
        </h3>
        <span
          v-if="status === 'ready' && data?.snapshot_time"
          class="text-xs text-gray-400 tabular-nums"
        >
          更新时间 {{ fmtClock(data.snapshot_time) }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-1">
        板块资金 → 基金映射 · 非投资建议
      </p>
    </header>

    <div class="p-4 space-y-5">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p
          v-if="
            data.snapshot_time === null
            || (data.holdings.length === 0 && data.candidates.length === 0)
          "
          class="text-gray-400 text-sm"
        >
          暂无盘中雷达数据,请等待交易时间采集
        </p>
        <template v-else>
          <!-- 我的持仓 -->
          <div>
            <h4 class="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
              我的持仓
              <span class="text-xs text-gray-400 tabular-nums">
                ({{ data.holdings.length }})
              </span>
            </h4>
            <p
              v-if="data.holdings.length === 0"
              class="text-xs text-gray-400"
            >
              无持仓基金踩中当前强势板块
            </p>
            <ul v-else class="divide-y divide-gray-100">
              <li
                v-for="item in data.holdings"
                :key="`h-${item.fund_code}`"
                class="py-2.5 flex items-start gap-3"
              >
                <span
                  class="text-xs px-1.5 py-0.5 rounded border tabular-nums whitespace-nowrap shrink-0"
                  :class="scoreChipClass(item.score)"
                  title="客观雷达分(rank_score + inflow_score 封顶 9),不是买卖建议"
                >
                  {{ item.score }}/9
                </span>
                <div class="flex-1 min-w-0">
                  <div class="flex items-start justify-between gap-2">
                    <div class="text-sm text-gray-800 font-medium truncate flex-1">
                      {{ item.fund_name }}
                    </div>
                    <span
                      class="text-[10px] leading-none px-1.5 py-1 rounded border whitespace-nowrap shrink-0"
                      :class="badgeClass(item.badge)"
                    >
                      {{ item.badge }}
                    </span>
                  </div>
                  <div class="text-xs text-gray-500 mt-0.5 tabular-nums">
                    {{ item.fund_code }}
                    <span class="text-gray-300 mx-1">·</span>
                    <span class="text-gray-700 font-medium">{{ item.matched_sector }}</span>
                    <span class="text-gray-300 mx-1">·</span>
                    板块 #{{ item.sector_rank }}
                  </div>
                  <div class="text-xs mt-1 tabular-nums flex items-center justify-between">
                    <span :class="inflowColor(item.sector_main_inflow_yi)" class="font-semibold">
                      主力净流入 {{ fmtYi(item.sector_main_inflow_yi) }}
                    </span>
                    <span class="text-gray-500">
                      涨跌
                      <span :class="pctColor(item.sector_change_pct)">
                        {{ fmtPct(item.sector_change_pct) }}
                      </span>
                    </span>
                  </div>
                </div>
              </li>
            </ul>
          </div>

          <!-- 候选基金 -->
          <div>
            <h4 class="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
              候选基金
              <span class="text-xs text-gray-400 tabular-nums">
                ({{ data.candidates.length }})
              </span>
            </h4>
            <p
              v-if="data.candidates.length === 0"
              class="text-xs text-gray-400"
            >
              无候选基金踩中当前强势板块
            </p>
            <ul v-else class="divide-y divide-gray-100">
              <li
                v-for="item in data.candidates"
                :key="`c-${item.fund_code}`"
                class="py-2.5 flex items-start gap-3"
              >
                <span
                  class="text-xs px-1.5 py-0.5 rounded border tabular-nums whitespace-nowrap shrink-0"
                  :class="scoreChipClass(item.score)"
                  title="客观雷达分(rank_score + inflow_score 封顶 9),不是买卖建议"
                >
                  {{ item.score }}/9
                </span>
                <div class="flex-1 min-w-0">
                  <div class="flex items-start justify-between gap-2">
                    <div class="text-sm text-gray-800 font-medium truncate flex-1">
                      {{ item.fund_name }}
                    </div>
                    <span
                      class="text-[10px] leading-none px-1.5 py-1 rounded border whitespace-nowrap shrink-0"
                      :class="badgeClass(item.badge)"
                    >
                      {{ item.badge }}
                    </span>
                  </div>
                  <div class="text-xs text-gray-500 mt-0.5 tabular-nums">
                    {{ item.fund_code }}
                    <span class="text-gray-300 mx-1">·</span>
                    <span class="text-gray-700 font-medium">{{ item.matched_sector }}</span>
                    <span class="text-gray-300 mx-1">·</span>
                    板块 #{{ item.sector_rank }}
                  </div>
                  <div class="text-xs mt-1 tabular-nums flex items-center justify-between">
                    <span :class="inflowColor(item.sector_main_inflow_yi)" class="font-semibold">
                      主力净流入 {{ fmtYi(item.sector_main_inflow_yi) }}
                    </span>
                    <span class="text-gray-500">
                      涨跌
                      <span :class="pctColor(item.sector_change_pct)">
                        {{ fmtPct(item.sector_change_pct) }}
                      </span>
                    </span>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>
