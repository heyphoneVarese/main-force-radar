<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b sticky top-0 z-10">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
        <div class="flex items-center gap-6 min-w-0">
          <h1 class="text-xl font-bold text-gray-900 whitespace-nowrap">主力风向标</h1>
          <nav class="flex gap-1 text-sm">
            <RouterLink to="/" class="nav-link">Dashboard</RouterLink>
            <RouterLink to="/holdings" class="nav-link">Holdings</RouterLink>
            <RouterLink to="/settings" class="nav-link">Settings</RouterLink>
          </nav>
        </div>
        <span class="text-xs text-gray-400 whitespace-nowrap">Phase 5.1 Dashboard</span>
      </div>
    </header>
    <main class="max-w-7xl mx-auto px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
/* 用 :deep + 全局类不方便,直接走 scoped + Vue Router 默认 active class */
.nav-link {
  @apply px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors;
}
/* router-link-exact-active 是 Vue Router 默认给精确匹配路由加的类。
   只用 exact-active 而不是 active,避免 "/" 在所有页面都高亮(因为
   "/" 是所有路径的前缀,会被 router-link-active 误判)。 */
.nav-link.router-link-exact-active {
  @apply bg-blue-50 text-blue-700 font-medium;
}
</style>
