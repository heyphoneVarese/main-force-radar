<script setup lang="ts">
import Holdings from './views/Holdings.vue'
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b sticky top-0 z-10">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <h1 class="text-xl font-bold text-gray-900">主力风向标</h1>
        <span class="text-xs text-gray-400">Phase 2.5b</span>
      </div>
    </header>
    <main class="max-w-7xl mx-auto px-4 py-6">
      <Holdings />
    </main>
  </div>
</template>
