<script setup lang="ts">
import type {
  SectorPersistenceLeaderItem,
  SectorPersistenceLeadersResponse,
} from '../../types'

// 连续Top20排行榜(PR22)— 把"持续出现的主线"按客观计数事实排出来,
// **不按今日 inflow 排**,避免被单日资金噪音盖过长期趋势。
//
// R3 红线:
//  - 全部是客观事实计数(continuous_*_days / last_N_*_days)
//  - badge 文案只是"持续出现/长期连续/普通"这种事实标签,不是评分,
//    不出现 buy/sell/long/short/hold/加仓/减仓/继续持有/推荐/建议/强烈
//    看多/看空 等词
//  - latest_rank 只是"今日的位置"参考,不是排序依据
//
// 数据源:GET /api/dashboard/sectors/persistence/leaders
// (后端 sector_persistence service 复用 _load_context + _compute_facts)

defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: SectorPersistenceLeadersResponse | null
  error: string
}>()

function fmtYi(yi: string | null | undefined): string {
  if (yi === null || yi === undefined) return 'n/a'
  const n = Number(yi)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}亿`
}

function inflowColor(yi: string | null | undefined): string {
  if (yi === null || yi === undefined) return 'text-gray-500'
  const n = Number(yi)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

// 客观事实徽章(spec):
//   >=20 → 长期连续(深紫)
//   >=10 → 持续出现(紫)
//   >=3  → 在场(淡紫)
//   <3   → 普通(灰)
// 全部是"在场/连续"事实标签,不是评分或建议。
interface Badge {
  text: string
  cls: string
}
function streakBadge(days: number): Badge {
  if (days >= 20) {
    return {
      text: '长期连续',
      cls: 'bg-purple-100 text-purple-800 border border-purple-200',
    }
  }
  if (days >= 10) {
    return {
      text: '持续出现',
      cls: 'bg-purple-50 text-purple-700 border border-purple-100',
    }
  }
  if (days >= 3) {
    return {
      text: '在场',
      cls: 'bg-indigo-50 text-indigo-700 border border-indigo-100',
    }
  }
  return {
    text: '普通',
    cls: 'bg-gray-50 text-gray-500 border border-gray-200',
  }
}

// 第二行事实串(只读、不评价):
//   连续Top20 N 天 · 近20 Top20 X 天 · 近20 流入 Y 天
function factsLine(item: SectorPersistenceLeaderItem): string {
  return (
    `连续Top20 ${item.continuous_top20_days} 天 · ` +
    `近20 Top20 ${item.last_20_top20_days} 天 · ` +
    `近20 流入 ${item.last_20_inflow_days} 天`
  )
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="px-4 py-3 border-b bg-gray-50/50">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span class="inline-block w-1.5 h-4 bg-purple-500 rounded-sm"></span>
          连续Top20排行榜
        </h3>
        <span
          v-if="status === 'ready' && data?.trade_date"
          class="text-xs text-gray-400 tabular-nums"
        >
          截至 {{ data.trade_date }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mt-1">
        默认显示连续Top20 ≥{{ data?.min_days ?? 3 }}天的板块
      </p>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">加载中...</p>
      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>
      <template v-else-if="data">
        <p v-if="data.items.length === 0" class="text-gray-400 text-sm">
          暂无连续Top20 ≥{{ data.min_days }}天的板块
        </p>
        <template v-else>
          <p class="text-xs text-gray-400 mb-2 tabular-nums">
            共 {{ data.items.length }} 条 · 过滤 ≥{{ data.min_days }}天 · 按连续天数排
          </p>
          <ul class="divide-y divide-gray-100">
            <li
              v-for="(item, idx) in data.items"
              :key="item.sector_code"
              class="py-2.5"
            >
              <!-- 上行:#leader_rank + 名称 + badge + 今日 inflow -->
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-2 min-w-0 flex-1">
                  <span
                    class="text-xs text-gray-400 tabular-nums w-6 text-right shrink-0"
                  >
                    #{{ idx + 1 }}
                  </span>
                  <span class="text-sm text-gray-800 font-medium truncate">
                    {{ item.sector_name }}
                  </span>
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded shrink-0 leading-none"
                    :class="streakBadge(item.continuous_top20_days).cls"
                  >
                    {{ streakBadge(item.continuous_top20_days).text }}
                  </span>
                </div>
                <span
                  class="text-sm font-semibold whitespace-nowrap tabular-nums"
                  :class="inflowColor(item.latest_main_inflow_yi)"
                >
                  {{ fmtYi(item.latest_main_inflow_yi) }}
                </span>
              </div>

              <!-- 第 2 行:事实串 + 今日位置 -->
              <div
                class="flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums mt-1 pl-8"
              >
                <span class="text-gray-600">{{ factsLine(item) }}</span>
                <span class="text-gray-300">·</span>
                <span class="text-gray-400">
                  今日#{{ item.latest_rank }}
                </span>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </div>
  </section>
</template>
