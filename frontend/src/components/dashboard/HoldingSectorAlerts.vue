<script setup lang="ts">
import { ref } from 'vue'
import type {
  HoldingSectorAlertsResponse,
  HoldingSectorAlertType,
} from '../../types'

// 持仓-板块事实提醒(PR23 + PR24.1 可展开)。把板块连续性事实 + 盘中
// 实时变动连接到我的持仓,生成中性事实提示。
//
// R3 红线:
//  - alert_type 是内部分类标签,不等于买卖信号
//  - badge 文案是中性事实标签(盘中流出/流入/连续流出/持仓集中),
//    **不出现** 买入/卖出/加仓/减仓/推荐/建议/看多/看空/危险/机会/应该
//  - holding_count、连续天数都是客观计数
//
// PR24.1 UX:每条卡默认收起(只显示极简事实);点击卡顶部或"查看详情"
// 展开详情(完整 message + 全部 fund_names + 完整 persistence facts)。
// 每条卡独立(用 Set<sector_code> 跟踪),状态在组件实例内 — 重新拉取
// 数据不会保留(可接受,默认全收起)。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: HoldingSectorAlertsResponse | null
  error: string
}>()

// alert_type → 中性标签(spec 文案)
const ALERT_LABELS: Record<HoldingSectorAlertType, string> = {
  intraday_outflow_on_long_persistence: '盘中流出',
  intraday_inflow_on_long_persistence: '盘中流入',
  continuous_outflow_holding_sector: '连续流出',
  concentrated_holding_sector: '持仓集中',
}

// 按 alert_type 着色 — amber/orange 主题做"留意"提示,不警告化
function alertChipClass(t: HoldingSectorAlertType): string {
  switch (t) {
    case 'intraday_outflow_on_long_persistence':
      return 'bg-orange-50 text-orange-700 border border-orange-200'
    case 'intraday_inflow_on_long_persistence':
      return 'bg-rose-50 text-rose-700 border border-rose-200'
    case 'continuous_outflow_holding_sector':
      return 'bg-amber-50 text-amber-700 border border-amber-200'
    case 'concentrated_holding_sector':
      return 'bg-yellow-50 text-yellow-700 border border-yellow-200'
  }
}

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

// PR24.1:用 Set<sector_code> 跟踪展开状态;每条独立
const expandedSectorCodes = ref<Set<string>>(new Set())

function isExpanded(code: string): boolean {
  return expandedSectorCodes.value.has(code)
}

function toggle(code: string): void {
  const next = new Set(expandedSectorCodes.value)
  if (next.has(code)) {
    next.delete(code)
  } else {
    next.add(code)
  }
  expandedSectorCodes.value = next
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-amber-50/40">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span class="inline-block w-1.5 h-4 bg-amber-500 rounded-sm"></span>
          持仓-板块事实提醒
        </h3>
        <span
          v-if="status === 'ready' && data?.trade_date"
          class="text-xs text-gray-400 tabular-nums"
        >
          截至 {{ data.trade_date }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-1">
        把板块资金变化连接到我的持仓,不构成投资建议
      </p>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.items.length === 0" class="text-gray-400 text-sm">
          暂无提醒(可能:无持仓 / 收盘数据未到 / 暂无关联板块到达触发门槛)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ data.items.length }} 条 · 点击展开详情
          </p>
          <ul class="space-y-3">
            <li
              v-for="item in data.items"
              :key="item.sector_code"
              class="rounded-md border border-gray-100 bg-gray-50/50 overflow-hidden"
            >
              <!-- 顶部区(始终可见):点击切展开 -->
              <button
                type="button"
                class="w-full text-left p-3 hover:bg-gray-100/60 transition-colors focus:outline-none focus:bg-gray-100/70"
                :aria-expanded="isExpanded(item.sector_code)"
                :aria-controls="`alert-detail-${item.sector_code}`"
                @click="toggle(item.sector_code)"
              >
                <!-- 第 1 行:板块名 + chip + 盘中数 -->
                <div class="flex items-center justify-between gap-3 flex-wrap">
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="text-sm font-semibold text-gray-800 truncate">
                      {{ item.sector_name }}
                    </span>
                    <span
                      class="text-[11px] px-1.5 py-0.5 rounded shrink-0 leading-none"
                      :class="alertChipClass(item.alert_type)"
                    >
                      {{ ALERT_LABELS[item.alert_type] }}
                    </span>
                  </div>
                  <span
                    v-if="item.intraday_main_inflow_yi !== null"
                    class="text-sm font-semibold whitespace-nowrap tabular-nums"
                    :class="inflowColor(item.intraday_main_inflow_yi)"
                  >
                    {{ fmtYi(item.intraday_main_inflow_yi) }}
                  </span>
                  <span v-else class="text-xs text-gray-400 whitespace-nowrap">
                    盘中暂无
                  </span>
                </div>

                <!-- 第 2 行:极简事实 -->
                <div
                  class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-gray-600 mt-1.5"
                >
                  <span>持有 {{ item.holding_count }} 只</span>
                  <span class="text-gray-300">·</span>
                  <span>连续Top20 {{ item.continuous_top20_days }} 天</span>
                </div>

                <!-- 第 3 行:展开/收起触发 -->
                <div class="mt-2 flex items-center justify-end">
                  <span
                    class="text-xs text-amber-700 inline-flex items-center gap-0.5 select-none"
                  >
                    {{ isExpanded(item.sector_code) ? '收起' : '查看详情' }}
                    <svg
                      class="w-3 h-3 transition-transform"
                      :class="isExpanded(item.sector_code) ? 'rotate-180' : ''"
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
                  </span>
                </div>
              </button>

              <!-- 展开区(详情)— 用 max-height transition 做简单动画 -->
              <div
                :id="`alert-detail-${item.sector_code}`"
                class="transition-all duration-200 ease-out overflow-hidden"
                :class="
                  isExpanded(item.sector_code)
                    ? 'max-h-[2000px] opacity-100'
                    : 'max-h-0 opacity-0'
                "
              >
                <div class="px-3 pb-3 pt-1 border-t border-gray-100 bg-white">
                  <!-- 完整 message -->
                  <p class="text-sm text-gray-700 leading-relaxed">
                    {{ item.message }}
                  </p>

                  <!-- 详细事实 -->
                  <div class="mt-3">
                    <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      详细事实
                    </h4>
                    <dl
                      class="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 text-sm tabular-nums"
                    >
                      <dt class="text-gray-500">连续Top20</dt>
                      <dd class="text-gray-800">{{ item.continuous_top20_days }} 天</dd>

                      <dt class="text-gray-500">连续流入</dt>
                      <dd class="text-gray-800">{{ item.continuous_inflow_days }} 天</dd>

                      <dt class="text-gray-500">连续流出</dt>
                      <dd class="text-gray-800">{{ item.continuous_outflow_days }} 天</dd>

                      <dt class="text-gray-500">近20日Top20</dt>
                      <dd class="text-gray-800">{{ item.last_20_top20_days }} 次</dd>

                      <dt class="text-gray-500">近20日流入</dt>
                      <dd class="text-gray-800">{{ item.last_20_inflow_days }} 天</dd>

                      <dt class="text-gray-500">近20日流出</dt>
                      <dd class="text-gray-800">{{ item.last_20_outflow_days }} 天</dd>

                      <template v-if="item.intraday_rank !== null">
                        <dt class="text-gray-500">盘中行业排名</dt>
                        <dd class="text-gray-800">#{{ item.intraday_rank }}</dd>
                      </template>
                      <template v-if="item.intraday_change_pct !== null">
                        <dt class="text-gray-500">盘中涨跌</dt>
                        <dd class="text-gray-800">
                          {{ Number(item.intraday_change_pct).toFixed(2) }}%
                        </dd>
                      </template>
                    </dl>
                  </div>

                  <!-- 关联基金 -->
                  <div class="mt-3">
                    <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      关联基金({{ item.holding_fund_names.length }})
                    </h4>
                    <p
                      v-if="item.holding_fund_names.length === 0"
                      class="text-sm text-gray-400 mt-1.5"
                    >
                      暂无关联基金名称
                    </p>
                    <ul v-else class="mt-1.5 space-y-1 text-sm text-gray-700">
                      <li
                        v-for="(name, idx) in item.holding_fund_names"
                        :key="`${item.sector_code}-${idx}`"
                        class="flex items-start gap-2"
                      >
                        <span class="text-amber-500 shrink-0">•</span>
                        <span class="break-all">{{ name }}</span>
                      </li>
                    </ul>
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
