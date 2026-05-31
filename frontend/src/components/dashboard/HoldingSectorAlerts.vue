<script setup lang="ts">
import type {
  HoldingSectorAlertItem,
  HoldingSectorAlertsResponse,
  HoldingSectorAlertType,
} from '../../types'

// 持仓-板块事实提醒(PR23)— 把板块连续性事实 + 盘中实时变动连接到
// 我的持仓,生成中性事实提示。
//
// R3 红线:
//  - alert_type 是内部分类标签,不等于买卖信号
//  - badge 文案是中性事实标签(盘中流出/流入/连续流出/持仓集中),
//    **不出现** 买入/卖出/加仓/减仓/推荐/建议/看多/看空/危险/机会/应该
//  - holding_count、连续天数都是客观计数
//
// 数据源:GET /api/dashboard/holding-sector-alerts

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

// 按 alert_type 着色 — 用 amber/orange 主题做"留意"提示,不警告化
function alertChipClass(t: HoldingSectorAlertType): string {
  switch (t) {
    case 'intraday_outflow_on_long_persistence':
      // 流出 + 长期主线 → 橙色(留意,但不"危险")
      return 'bg-orange-50 text-orange-700 border border-orange-200'
    case 'intraday_inflow_on_long_persistence':
      // 流入 → 红色(A 股配色:红涨)但偏淡
      return 'bg-rose-50 text-rose-700 border border-rose-200'
    case 'continuous_outflow_holding_sector':
      // 连续流出 → 琥珀色
      return 'bg-amber-50 text-amber-700 border border-amber-200'
    case 'concentrated_holding_sector':
      // 持仓集中 → 黄色(仅提示集中度)
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

// 前端最多显示 3 个基金名,其余显示 "等 X 只"
function fundNamesPreview(item: HoldingSectorAlertItem): string {
  const names = item.holding_fund_names
  if (names.length === 0) return ''
  if (names.length <= 3) return names.join('、')
  return `${names.slice(0, 3).join('、')} 等 ${names.length} 只`
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
            共 {{ data.items.length }} 条
          </p>
          <ul class="space-y-3">
            <li
              v-for="item in data.items"
              :key="item.sector_code"
              class="rounded-md border border-gray-100 bg-gray-50/50 p-3"
            >
              <!-- 第 1 行:板块 + alert chip + 盘中净流入 -->
              <div class="flex items-center justify-between gap-3 flex-wrap">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="text-sm font-semibold text-gray-800 truncate">
                    {{ item.sector_name }}
                  </span>
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded shrink-0 leading-none"
                    :class="alertChipClass(item.alert_type)"
                  >
                    {{ ALERT_LABELS[item.alert_type] }}
                  </span>
                  <span class="text-xs text-gray-400 tabular-nums shrink-0">
                    持有 {{ item.holding_count }} 只
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

              <!-- 第 2 行:事实串(连续Top20 / 近20 Top20)-->
              <div
                class="flex flex-wrap items-center gap-x-3 text-xs tabular-nums text-gray-600 mt-1.5"
              >
                <span>连续Top20 {{ item.continuous_top20_days }} 天</span>
                <span class="text-gray-300">·</span>
                <span>近20 Top20 {{ item.last_20_top20_days }} 次</span>
                <span class="text-gray-300">·</span>
                <span>近20 流入 {{ item.last_20_inflow_days }} 天</span>
              </div>

              <!-- 第 3 行:message(事实陈述)-->
              <p class="text-xs text-gray-700 mt-1.5 leading-relaxed">
                {{ item.message }}
              </p>

              <!-- 第 4 行:fund_names 前 3 -->
              <p
                v-if="item.holding_fund_names.length > 0"
                class="text-[11px] text-gray-500 mt-1 truncate"
                :title="item.holding_fund_names.join('、')"
              >
                {{ fundNamesPreview(item) }}
              </p>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
