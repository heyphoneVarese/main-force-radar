<script setup lang="ts">
import type { SectorTypeFilter } from '../../api/client'
import type { TopSectors as TopSectorsData } from '../../types'

// Top 20 板块卡(Phase 5.1 PR9)。
//
// Tab 状态管理:子组件只接 `currentType` prop,emit 'change-type' 让父
// 触发新一次 fetch。这样:
//  1. props 保持 {status, data, error} 三件套统一
//  2. 切换时父立刻把 sectorsStatus 改回 'loading',UI 自然过渡
//  3. 网络请求 + 缓存策略只在 Dashboard.vue 一处
//
// 显示策略:Top 20 全部列出,每行两行布局:
//   - 上行:#rank + sector_name + main_inflow_wan(主指标,大字红绿)
//   - 下行:涨跌幅 + 主力净流入占比(辅助指标,小字)
// 这样手机也能舒服显示,不挤在一行。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: TopSectorsData | null
  error: string
  currentType: SectorTypeFilter
}>()

const emit = defineEmits<{
  'change-type': [SectorTypeFilter]
}>()

const TABS: { value: SectorTypeFilter; label: string }[] = [
  { value: 'industry', label: '行业' },
  { value: 'concept', label: '概念' },
  { value: 'all', label: '全部' },
]

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
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="flex items-center justify-between px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-orange-500 rounded-sm"></span>
        Top 20 板块
      </h3>
      <nav class="flex gap-0.5 text-xs">
        <button
          v-for="tab in TABS"
          :key="tab.value"
          class="px-2.5 py-1 rounded transition-colors"
          :class="
            currentType === tab.value
              ? 'bg-orange-100 text-orange-700 font-medium'
              : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700'
          "
          @click="emit('change-type', tab.value)"
        >
          {{ tab.label }}
        </button>
      </nav>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.sectors.length === 0" class="text-gray-400 text-sm">
          暂无数据(等待 cron 15:20 采集完成)
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            截至 {{ data.trade_date }} · 共 {{ data.sectors.length }} 条
          </p>
          <ul class="divide-y divide-gray-100">
            <li v-for="s in data.sectors" :key="s.sector_code" class="py-2.5">
              <!-- 上行:rank + name + main_inflow_wan(主指标)-->
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-2 min-w-0">
                  <span
                    class="text-xs text-gray-400 tabular-nums w-7 text-right shrink-0"
                  >
                    #{{ s.rank }}
                  </span>
                  <span class="text-sm text-gray-800 font-medium truncate">
                    {{ s.sector_name }}
                  </span>
                </div>
                <span
                  class="text-sm font-semibold whitespace-nowrap tabular-nums"
                  :class="inflowColor(s.main_inflow_wan)"
                >
                  {{ fmtYi(s.main_inflow_wan) }}
                </span>
              </div>
              <!-- 下行:涨跌幅 + 净流入占比(辅助)-->
              <div
                class="flex justify-end gap-4 text-xs text-gray-500 tabular-nums mt-0.5 pl-9"
              >
                <span>
                  涨跌
                  <span :class="pctColor(s.change_pct)">{{ fmtPct(s.change_pct) }}</span>
                </span>
                <span>
                  占比
                  <span :class="pctColor(s.main_inflow_pct)">
                    {{ fmtPct(s.main_inflow_pct) }}
                  </span>
                </span>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
