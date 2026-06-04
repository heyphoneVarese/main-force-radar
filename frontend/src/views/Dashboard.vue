<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardApi } from '../api/client'
import HoldingSectorAlerts from '../components/dashboard/HoldingSectorAlerts.vue'
import TodayFlowTop10 from '../components/dashboard/TodayFlowTop10.vue'
import type { HoldingSectorAlertsResponse, TopSectors } from '../types'

// Dashboard 首页(Phase 2 瘦身):只保留 3 个模块。
//
//   1. 资金流入 Top10
//   2. 资金流出 Top10
//   3. 我的持仓提醒
//
// 连续性 → /continuity;板块趋势 → /trends;持仓分析 → /holdings。
// 每张卡 {status, data, error} 三件套独立 fetch,慢的不阻塞快的。

type Status = 'loading' | 'ready' | 'error'

const inflowStatus = ref<Status>('loading')
const inflowData = ref<TopSectors | null>(null)
const inflowError = ref('')

const outflowStatus = ref<Status>('loading')
const outflowData = ref<TopSectors | null>(null)
const outflowError = ref('')

const alertsStatus = ref<Status>('loading')
const alertsData = ref<HoldingSectorAlertsResponse | null>(null)
const alertsError = ref('')

function _errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

onMounted(() => {
  void Promise.allSettled([
    // 1. inflow Top10 — 后端 n=30,组件按符号过滤再裁前 10
    dashboardApi.topSectors(30, 'industry', 'inflow').then(
      (d) => { inflowData.value = d; inflowStatus.value = 'ready' },
      (e) => { inflowError.value = _errMsg(e); inflowStatus.value = 'error' },
    ),
    // 2. outflow Top10
    dashboardApi.topSectors(30, 'industry', 'outflow').then(
      (d) => { outflowData.value = d; outflowStatus.value = 'ready' },
      (e) => { outflowError.value = _errMsg(e); outflowStatus.value = 'error' },
    ),
    // 3. 我的持仓提醒
    dashboardApi.holdingSectorAlerts(10).then(
      (d) => { alertsData.value = d; alertsStatus.value = 'ready' },
      (e) => { alertsError.value = _errMsg(e); alertsStatus.value = 'error' },
    ),
  ])
})
</script>

<template>
  <div class="space-y-4">
    <!-- 第 1 屏:Top10 inflow + outflow -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <TodayFlowTop10
        :status="inflowStatus"
        :data="inflowData"
        :error="inflowError"
        order="inflow"
      />
      <TodayFlowTop10
        :status="outflowStatus"
        :data="outflowData"
        :error="outflowError"
        order="outflow"
      />
    </div>

    <!-- 第 2 屏:我的持仓提醒 -->
    <HoldingSectorAlerts
      :status="alertsStatus"
      :data="alertsData"
      :error="alertsError"
    />
  </div>
</template>
