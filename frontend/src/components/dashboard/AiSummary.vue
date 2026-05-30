<script setup lang="ts">
import { computed } from 'vue'
import type { AISummary } from '../../types'

// AI 一句话结论卡(Phase 5.1 PR8)。
//
// 视觉:左侧 1.5px 蓝色装饰条 + summary 大字 + 底部相对时间(刚刚/N 分钟前)。
// cached chip 区分本次新调用 vs 24h 缓存命中,帮用户判断"AI 是不是又付费跑了"。

const props = defineProps<{
  status: 'loading' | 'ready' | 'error'
  data: AISummary | null
  error: string
}>()

const relativeTime = computed((): string => {
  if (!props.data?.generated_at) return ''
  const gen = new Date(props.data.generated_at)
  const now = new Date()
  const diffSec = Math.floor((now.getTime() - gen.getTime()) / 1000)
  // 防 clock skew:服务器或客户端时钟略偏 → 负值当"刚刚"
  if (diffSec < 60) return '刚刚'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`
  return `${Math.floor(diffSec / 86400)} 天前`
})

function fmtAbsTime(iso: string): string {
  // ISO with TZ → "YYYY-MM-DD HH:MM"
  return iso.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <section class="bg-white rounded-lg shadow-sm border overflow-hidden">
    <header class="flex items-center justify-between px-4 py-3 border-b bg-gray-50/50">
      <h3 class="text-base font-semibold text-gray-900 flex items-center gap-2">
        <span class="inline-block w-1.5 h-4 bg-blue-500 rounded-sm"></span>
        AI 结论
      </h3>
      <span
        v-if="status === 'ready' && data?.cached"
        class="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 border border-blue-100"
        title="本次返回命中 24h 缓存,未触发 Claude API 调用"
      >
        cached
      </span>
    </header>

    <div class="p-4">
      <p v-if="status === 'loading'" class="text-gray-400 text-sm">
        加载中(AI 调用通常 1-3 秒)...
      </p>

      <p v-else-if="status === 'error'" class="text-red-500 text-sm">
        ⚠ {{ error }}
      </p>

      <template v-else-if="data">
        <p v-if="!data.summary" class="text-gray-400 text-sm">暂无 AI 结论</p>
        <template v-else>
          <p class="text-gray-800 leading-relaxed text-[15px]">
            {{ data.summary }}
          </p>
          <div
            class="text-xs text-gray-400 mt-3 flex flex-wrap items-center gap-x-2 gap-y-1"
          >
            <span>生成于 {{ relativeTime }}</span>
            <span class="text-gray-300">·</span>
            <span class="tabular-nums">{{ fmtAbsTime(data.generated_at) }}</span>
            <span
              v-if="data.trade_date"
              class="text-gray-300"
            >·</span>
            <span v-if="data.trade_date" class="tabular-nums">
              数据 {{ data.trade_date }}
            </span>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>
