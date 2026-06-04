<script setup lang="ts">
import type { FreshnessInfo, TimeMeta } from '../../types'

const props = defineProps<{
  timeMeta?: TimeMeta | null
  freshness?: FreshnessInfo | null
}>()

function meta(): TimeMeta | null {
  if (props.timeMeta) return props.timeMeta
  if (!props.freshness) return null
  return {
    data_date: props.freshness.data_date,
    data_time: props.freshness.data_time,
    source_type: props.freshness.source_type,
    updated_at: props.freshness.updated_at,
    is_fresh: props.freshness.is_fresh,
    reason: props.freshness.reason,
  }
}

function sourceLabel(source: string): string {
  if (source === 'intraday') return '盘中'
  if (source === 'daily_close') return '收盘'
  if (source === 'cached') return '缓存'
  return '过期'
}

function fmtUpdatedAt(v: string | null): string {
  if (!v) return '--'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<template>
  <div
    v-if="meta()"
    class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-gray-500 tabular-nums"
    :title="meta()?.reason"
  >
    <span>数据日期: {{ meta()?.data_date ?? '--' }}</span>
    <span v-if="meta()?.data_time">数据时间: {{ meta()?.data_time }}</span>
    <span>来源: {{ sourceLabel(meta()?.source_type ?? 'stale') }}</span>
    <span>更新: {{ fmtUpdatedAt(meta()?.updated_at ?? null) }}</span>
    <span
      class="px-1.5 py-0.5 rounded border"
      :class="
        meta()?.is_fresh
          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
          : 'bg-amber-50 text-amber-700 border-amber-200'
      "
    >
      {{ meta()?.is_fresh ? '新鲜' : '过期' }}
    </span>
  </div>
</template>
