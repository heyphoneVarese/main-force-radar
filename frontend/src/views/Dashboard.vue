<script setup lang="ts">
// PR6 占位。PR7 接入 dashboardApi 后渲染 5 个数据卡片:
//   <MarketTemp />      ← GET /api/dashboard/market
//   <AiSummary />       ← GET /api/dashboard/ai-summary
//   <TopSectors />      ← GET /api/dashboard/sectors/top
//   <TopFunds />        ← GET /api/dashboard/funds/top
//   <MyHoldingsTable /> ← GET /api/dashboard/holdings-summary
</script>

<template>
  <div class="space-y-4">
    <h2 class="text-xl font-semibold text-gray-900">Dashboard</h2>
    <p class="text-gray-500">
      Phase 5.1 骨架已就绪。PR7 接入 5 个 dashboard API 后,这里将渲染:
    </p>
    <ul class="text-gray-500 text-sm space-y-1 list-disc pl-5">
      <li>今日市场温度(上证 / 深成 / 创业板 / 沪深300)</li>
      <li>AI 一句话结论(24h 缓存)</li>
      <li>Top 20 板块(主力净流入降序)</li>
      <li>Top 20 基金(映射板块强度)</li>
      <li>我的持仓信号分析</li>
    </ul>
  </div>
</template>
