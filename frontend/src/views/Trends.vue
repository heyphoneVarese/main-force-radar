<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { dashboardApi } from '../api/client'
import CapitalMigrationRadar from '../components/dashboard/CapitalMigrationRadar.vue'
import SectorDetailList from '../components/dashboard/SectorDetailList.vue'
import type { CapitalMigrationResponse, SectorTrendsResponse } from '../types'

// /trends — 板块趋势 + 20天资金历史 + sparkline + 二级展开明细
// (Phase 2 拆分:从 Dashboard 迁出)。

type Status = 'loading' | 'ready' | 'error'

const status = ref<Status>('loading')
const data = ref<SectorTrendsResponse | null>(null)
const error = ref('')

const migrationStatus = ref<Status>('loading')
const migrationData = ref<CapitalMigrationResponse | null>(null)
const migrationError = ref('')

function _errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

onMounted(() => {
  void Promise.allSettled([
    dashboardApi.capitalMigration(10, 'industry', 20).then(
      (d) => {
        migrationData.value = d
        migrationStatus.value = 'ready'
      },
      (e) => {
        migrationError.value = _errMsg(e)
        migrationStatus.value = 'error'
      },
    ),
    dashboardApi.sectorTrends(10, 'industry').then(
      (d) => {
        data.value = d
        status.value = 'ready'
      },
      (e) => {
        error.value = _errMsg(e)
        status.value = 'error'
      },
    ),
  ])
})
</script>

<template>
  <div class="space-y-4">
    <header class="mb-2">
      <h2 class="text-xl font-semibold text-gray-900">板块趋势</h2>
      <p class="text-xs text-gray-500 mt-1">
        点击板块展开 sparkline,再点"查看明细" 看 20 日表格
      </p>
    </header>
    <CapitalMigrationRadar
      :status="migrationStatus"
      :data="migrationData"
      :error="migrationError"
    />
    <SectorDetailList
      :status="status"
      :data="data"
      :error="error"
    />
  </div>
</template>
