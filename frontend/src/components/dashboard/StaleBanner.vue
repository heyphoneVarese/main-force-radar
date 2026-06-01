<script setup lang="ts">
import type { FreshnessInfo } from '../../types'

// P0 fix:数据新鲜度提示横条。is_fresh=false 时显示淡黄色 banner,
// 内容仍正常渲染下方(不做硬遮挡,保留诊断价值)。
//
// 不渲染时:freshness 为 null/undefined,或 is_fresh=true。

defineProps<{
  freshness: FreshnessInfo | null | undefined
}>()

function formatTime(t: string | null, source: string): string {
  if (!t) return ''
  // intraday → 2026-06-01 14:30
  // daily    → 2026-06-01
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const pad = (n: number) => String(n).padStart(2, '0')
  const ymd = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  if (source === 'intraday') {
    return `${ymd} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  return ymd
}
</script>

<template>
  <div
    v-if="freshness && !freshness.is_fresh"
    class="mb-3 px-3 py-2 rounded-md border border-amber-300 bg-amber-50 text-amber-800 text-xs"
    role="status"
  >
    <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span class="font-semibold">⚠ 数据可能过期</span>
      <span v-if="freshness.latest_time" class="tabular-nums">
        · 最新 {{ formatTime(freshness.latest_time, freshness.source) }}
      </span>
      <span v-if="freshness.age_minutes !== null" class="text-amber-700 tabular-nums">
        · {{ freshness.age_minutes }} 分钟前
      </span>
    </div>
    <p class="mt-0.5 text-[11px] text-amber-700 leading-snug">
      {{ freshness.reason }}
    </p>
  </div>
</template>
