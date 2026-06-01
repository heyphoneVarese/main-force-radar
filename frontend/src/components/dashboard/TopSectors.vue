<script setup lang="ts">
import { computed } from 'vue'
import type { SectorTypeFilter } from '../../api/client'
import type {
  IntradayTopSectors,
  TopSectors as TopSectorsData,
} from '../../types'
import StaleBanner from './StaleBanner.vue'

// Top 20 板块卡(Phase 5.1 PR9 + PR15)。
//
// PR15 新增 mode toggle:
//   - 'intraday' 显示 intradayData(API: /dashboard/intraday/sectors/top)
//   - 'daily' 显示 data(API: /dashboard/sectors/top)
// 父决定默认 mode + 触发 fetch;本组件只切换渲染源 + emit user 切换意图。
//
// Tab 状态管理(原 PR9):子组件只接 `currentType` prop,emit
// 'change-type' 让父触发新一次 fetch。props 保持 {status, data, error}
// 三件套统一,intraday 的三件套作为额外 prop。

const props = defineProps<{
  // 原 daily 三件套
  status: 'loading' | 'ready' | 'error'
  data: TopSectorsData | null
  error: string
  // 新 intraday 三件套(PR15)
  intradayStatus: 'loading' | 'ready' | 'error'
  intradayData: IntradayTopSectors | null
  intradayError: string
  // 板块类型 tab + 数据模式 mode
  currentType: SectorTypeFilter
  currentMode: 'intraday' | 'daily'
}>()

const emit = defineEmits<{
  'change-type': [SectorTypeFilter]
  'change-mode': ['intraday' | 'daily']
}>()

// 当前模式下要展示的数据(简化模板里的条件分支)
const activeStatus = computed(() =>
  props.currentMode === 'intraday' ? props.intradayStatus : props.status
)
const activeError = computed(() =>
  props.currentMode === 'intraday' ? props.intradayError : props.error
)
// 用通用 sectors[] / trade_date 形态;intraday 额外有 snapshot_time
const activeSectors = computed(() => {
  if (props.currentMode === 'intraday') {
    return props.intradayData?.sectors ?? []
  }
  return props.data?.sectors ?? []
})
const activeTradeDate = computed(() => {
  if (props.currentMode === 'intraday') return props.intradayData?.trade_date ?? null
  return props.data?.trade_date ?? null
})
const activeSnapshotTime = computed(() =>
  props.currentMode === 'intraday'
    ? props.intradayData?.snapshot_time ?? null
    : null
)

function fmtClock(iso: string | null): string {
  // ISO datetime "2026-06-01T14:30:00" → "14:30"
  if (!iso) return ''
  return iso.slice(11, 16)
}

// 用户已点了 daily,但 intraday 库为空时给提示:
//   "暂无盘中数据,当前显示最近收盘数据"
// 跟父对齐 — 父在 intraday 空时自动 set currentMode='daily',
// 这里检测是否之前曾经尝试切到 intraday 但被自动 fallback。
// 简化:只在 daily 模式 + intradayStatus=ready + intradayData.sectors=[] 时
// 显示这条小字提示。
const showIntradayFallbackNote = computed(() => {
  return (
    props.currentMode === 'daily' &&
    props.intradayStatus === 'ready' &&
    (props.intradayData?.sectors?.length ?? 0) === 0
  )
})

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
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span class="inline-block w-1.5 h-4 bg-orange-500 rounded-sm"></span>
          Top 20 板块 ·
          <span class="text-orange-700">
            {{ currentMode === 'intraday' ? '盘中实时' : '收盘数据' }}
          </span>
        </h3>
        <nav class="flex gap-0.5 text-xs shrink-0">
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
      </div>
      <!-- PR15 mode toggle:盘中实时 / 收盘数据 -->
      <div class="flex items-center justify-between mt-2 text-xs">
        <nav class="flex gap-0.5">
          <button
            class="px-2.5 py-1 rounded transition-colors"
            :class="
              currentMode === 'intraday'
                ? 'bg-blue-100 text-blue-700 font-medium'
                : 'text-gray-500 hover:bg-gray-100'
            "
            @click="emit('change-mode', 'intraday')"
          >
            盘中实时
          </button>
          <button
            class="px-2.5 py-1 rounded transition-colors"
            :class="
              currentMode === 'daily'
                ? 'bg-gray-200 text-gray-700 font-medium'
                : 'text-gray-500 hover:bg-gray-100'
            "
            @click="emit('change-mode', 'daily')"
          >
            收盘数据
          </button>
        </nav>
        <span class="text-gray-400 tabular-nums">
          <template v-if="currentMode === 'intraday' && activeSnapshotTime">
            更新时间 {{ fmtClock(activeSnapshotTime) }}
          </template>
          <template v-else-if="currentMode === 'daily' && activeTradeDate">
            截至 {{ activeTradeDate }}
          </template>
        </span>
      </div>
    </header>

    <div class="p-4">
      <StaleBanner :freshness="data?.freshness" />
      <!-- PR15:盘中库空时给提示(daily 模式下渲染时) -->
      <p
        v-if="showIntradayFallbackNote"
        class="text-xs text-amber-600 bg-amber-50 border border-amber-100 rounded px-2 py-1 mb-2"
      >
        暂无盘中数据,当前显示最近收盘数据
      </p>

      <p v-if="activeStatus === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="activeStatus === 'error'" class="text-red-500 text-sm">
        ⚠ {{ activeError }}
      </p>
      <template v-else>
        <p v-if="activeSectors.length === 0" class="text-gray-400 text-sm">
          <template v-if="currentMode === 'intraday'">
            暂无盘中快照(非交易时间或集合竞价前)
          </template>
          <template v-else>
            暂无数据(等待 cron 15:20 采集完成)
          </template>
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ activeSectors.length }} 条
          </p>
          <ul class="divide-y divide-gray-100">
            <li v-for="s in activeSectors" :key="s.sector_code" class="py-2.5">
              <!-- 上行:rank + name + main_inflow_wan -->
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
              <!-- 下行:涨跌幅 + 净流入占比 -->
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
