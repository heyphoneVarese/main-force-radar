<script setup lang="ts">
import type { MarketSnapshot } from '../../types'

// 市场温度卡(Phase 5.1 PR8)。
//
// Props 接 Dashboard.vue 的状态机:status + 完整 data + error 字符串。
// 自带轻量格式化辅助 — 不抽公共 utils,保持组件自包含(R6 极简;
// PR9/10 如有重复再抽)。
//
// 视觉:每个指数一个色块,涨/跌/平 → 红/绿/灰底色 + 趋势箭头 ▲▼·。
// A 股惯例 = 红涨绿跌。

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: MarketSnapshot | null
  error: string
}>()

function fmtPct(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'n/a'
  const n = Number(decStr) * 100
  const sign = n > 0 ? '+' : ''  // 负号 toFixed 自带
  return `${sign}${n.toFixed(2)}%`
}

function fmtClose(decStr: string): string {
  return Number(decStr).toFixed(2)
}

function arrow(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return '·'
  const n = Number(decStr)
  if (n > 0) return '▲'
  if (n < 0) return '▼'
  return '·'
}

function textColor(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'text-gray-500'
  const n = Number(decStr)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function bgColor(decStr: string | null | undefined): string {
  if (decStr === null || decStr === undefined) return 'bg-gray-50'
  const n = Number(decStr)
  if (n > 0) return 'bg-red-50'
  if (n < 0) return 'bg-green-50'
  return 'bg-gray-50'
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="flex items-center justify-between px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-gray-700 rounded-sm"></span>
        今日市场温度
      </h3>
      <span
        v-if="status === 'ready' && data?.trade_date"
        class="text-xs text-gray-400 tabular-nums"
      >
        截至 {{ data.trade_date }}
      </span>
    </header>

    <div class="p-4">
      <!-- loading -->
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>

      <!-- error -->
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>

      <!-- ready: 空数据 -->
      <template v-else-if="data">
        <p v-if="data.trade_date === null" class="text-gray-400 text-sm">
          暂无数据(等待 cron 15:20 采集完成)
        </p>

        <!-- ready: 正常 -->
        <div v-else class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div
            v-for="idx in data.indices"
            :key="idx.index_code"
            class="rounded-md p-3 transition-colors"
            :class="bgColor(idx.change_pct)"
          >
            <div class="text-xs text-gray-500 mb-1 truncate">
              {{ idx.index_name }}
            </div>
            <div
              class="text-2xl font-bold leading-tight tabular-nums"
              :class="textColor(idx.change_pct)"
            >
              <span class="text-base">{{ arrow(idx.change_pct) }}</span>
              {{ fmtPct(idx.change_pct) }}
            </div>
            <div class="text-xs text-gray-400 mt-1 tabular-nums">
              {{ fmtClose(idx.close) }}
            </div>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>
