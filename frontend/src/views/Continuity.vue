<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardApi } from '../api/client'
import ContinuousFlowRank from '../components/dashboard/ContinuousFlowRank.vue'
import type { SectorPersistenceLeadersResponse } from '../types'

// /continuity — 连续流入 / 连续流出 排行(Phase 2 拆分:从 Dashboard 迁出)。

type Status = 'loading' | 'ready' | 'error'

const inflowStatus = ref<Status>('loading')
const inflowData = ref<SectorPersistenceLeadersResponse | null>(null)
const inflowError = ref('')

const outflowStatus = ref<Status>('loading')
const outflowData = ref<SectorPersistenceLeadersResponse | null>(null)
const outflowError = ref('')

function _errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

onMounted(() => {
  void Promise.allSettled([
    dashboardApi
      .sectorPersistenceLeaders(10, 'industry', 1, 'continuous_inflow')
      .then(
        (d) => {
          inflowData.value = d
          inflowStatus.value = 'ready'
        },
        (e) => {
          inflowError.value = _errMsg(e)
          inflowStatus.value = 'error'
        },
      ),
    dashboardApi
      .sectorPersistenceLeaders(10, 'industry', 1, 'continuous_outflow')
      .then(
        (d) => {
          outflowData.value = d
          outflowStatus.value = 'ready'
        },
        (e) => {
          outflowError.value = _errMsg(e)
          outflowStatus.value = 'error'
        },
      ),
  ])
})
</script>

<template>
  <div class="space-y-4">
    <header class="mb-2">
      <h2 class="text-xl font-semibold text-gray-900">连续性 · 资金</h2>
      <p class="text-xs text-gray-500 mt-1">
        基于 sector_flow_daily 历史 — 连续流入 / 流出排行
      </p>
    </header>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <ContinuousFlowRank
        :status="inflowStatus"
        :data="inflowData"
        :error="inflowError"
        direction="inflow"
      />
      <ContinuousFlowRank
        :status="outflowStatus"
        :data="outflowData"
        :error="outflowError"
        direction="outflow"
      />
    </div>
  </div>
</template>
