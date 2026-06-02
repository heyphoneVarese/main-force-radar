<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardApi } from '../api/client'
import ContinuousFlowRank from '../components/dashboard/ContinuousFlowRank.vue'
import SectorDetailList from '../components/dashboard/SectorDetailList.vue'
import TodayFlowTop10 from '../components/dashboard/TodayFlowTop10.vue'
import type {
  SectorPersistenceLeadersResponse,
  SectorTrendsResponse,
  TopSectors,
} from '../types'

// Dashboard 重构:只围绕 4 个问题
//   1. 今天主力买什么 → 今日资金流入 Top10
//   2. 今天主力卖什么 → 今日资金流出 Top10
//   3. 哪些板块连续流入 → 连续流入排行
//   4. 哪些板块连续流出 → 连续流出排行
//   + 第 3 部分:板块详情(折叠,20 日 sparkline)
//
// 不显示:AI summary / 市场点评 / 评分 / 买卖建议 / 情绪 / 预测。
// /holdings 是独立 page,不在 Dashboard 上。
//
// 每张卡 {status, data, error} 三件套独立 fetch,慢的不阻塞快的。

type Status = 'loading' | 'ready' | 'error'

// 第 1 屏:今日 inflow Top10
const inflowStatus = ref<Status>('loading')
const inflowData = ref<TopSectors | null>(null)
const inflowError = ref('')

// 第 1 屏:今日 outflow Top10
const outflowStatus = ref<Status>('loading')
const outflowData = ref<TopSectors | null>(null)
const outflowError = ref('')

// 第 2 部分:连续流入排行
const contInflowStatus = ref<Status>('loading')
const contInflowData = ref<SectorPersistenceLeadersResponse | null>(null)
const contInflowError = ref('')

// 第 2 部分:连续流出排行
const contOutflowStatus = ref<Status>('loading')
const contOutflowData = ref<SectorPersistenceLeadersResponse | null>(null)
const contOutflowError = ref('')

// 第 3 部分:板块详情(20 日趋势)
const trendsStatus = ref<Status>('loading')
const trendsData = ref<SectorTrendsResponse | null>(null)
const trendsError = ref('')

function _errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

onMounted(() => {
  void Promise.allSettled([
    // 1. inflow Top10 — 后端 n=30 给前端宽度,组件按符号过滤再裁前 10
    dashboardApi.topSectors(30, 'industry', 'inflow').then(
      (d) => { inflowData.value = d; inflowStatus.value = 'ready' },
      (e) => { inflowError.value = _errMsg(e); inflowStatus.value = 'error' },
    ),
    // 2. outflow Top10 — 同上
    dashboardApi.topSectors(30, 'industry', 'outflow').then(
      (d) => { outflowData.value = d; outflowStatus.value = 'ready' },
      (e) => { outflowError.value = _errMsg(e); outflowStatus.value = 'error' },
    ),
    // 3. 连续流入排行(min_days=1 显示所有有流入的;n=10)
    dashboardApi.sectorPersistenceLeaders(10, 'industry', 1, 'continuous_inflow').then(
      (d) => { contInflowData.value = d; contInflowStatus.value = 'ready' },
      (e) => { contInflowError.value = _errMsg(e); contInflowStatus.value = 'error' },
    ),
    // 4. 连续流出排行
    dashboardApi.sectorPersistenceLeaders(10, 'industry', 1, 'continuous_outflow').then(
      (d) => { contOutflowData.value = d; contOutflowStatus.value = 'ready' },
      (e) => { contOutflowError.value = _errMsg(e); contOutflowStatus.value = 'error' },
    ),
    // 5. 板块详情(20 天趋势)
    dashboardApi.sectorTrends(10, 'industry').then(
      (d) => { trendsData.value = d; trendsStatus.value = 'ready' },
      (e) => { trendsError.value = _errMsg(e); trendsStatus.value = 'error' },
    ),
  ])
})
</script>

<template>
  <div class="space-y-4">
    <!-- 第 1 屏:今日 Top10 inflow + outflow(桌面并排,移动端上下) -->
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

    <!-- 第 2 部分:连续流入 + 连续流出 排行 -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <ContinuousFlowRank
        :status="contInflowStatus"
        :data="contInflowData"
        :error="contInflowError"
        direction="inflow"
      />
      <ContinuousFlowRank
        :status="contOutflowStatus"
        :data="contOutflowData"
        :error="contOutflowError"
        direction="outflow"
      />
    </div>

    <!-- 第 3 部分:板块详情(折叠 + 20 日 sparkline) -->
    <SectorDetailList
      :status="trendsStatus"
      :data="trendsData"
      :error="trendsError"
    />
  </div>
</template>
