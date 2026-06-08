<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()
const navRef = ref<HTMLElement | null>(null)

watch(
  () => route.fullPath,
  async () => {
    await nextTick()
    navRef.value
      ?.querySelector('.router-link-exact-active')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  },
  { immediate: true },
)
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white border-b sticky top-0 z-10">
      <div class="max-w-7xl mx-auto px-4 py-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <div class="flex flex-col gap-2 min-w-0 sm:flex-row sm:items-center sm:gap-4 sm:flex-1">
          <h1 class="text-xl font-bold text-gray-900 whitespace-nowrap shrink-0">
            主力风向标
          </h1>
          <!-- Phase 2:nav 5 项,移动端横向滚动避免挤压副标题 -->
          <nav
            ref="navRef"
            class="flex w-full gap-0.5 sm:gap-1 text-sm overflow-x-auto min-w-0 nav-scroll"
          >
            <RouterLink to="/" class="nav-link">Dashboard</RouterLink>
            <RouterLink to="/continuity" class="nav-link">Continuity</RouterLink>
            <RouterLink to="/trends" class="nav-link">Trends</RouterLink>
            <RouterLink to="/holdings" class="nav-link">Holdings</RouterLink>
            <RouterLink to="/settings" class="nav-link">Settings</RouterLink>
          </nav>
        </div>
        <!-- 副标题:< sm (640px) 隐藏,腾位置给 nav,修复移动端挤压 -->
        <span
          class="text-xs text-gray-400 whitespace-nowrap shrink-0 hidden sm:inline"
        >
          Phase 5.1 Dashboard
        </span>
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
  @apply px-1 sm:px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors shrink-0;
}
/* router-link-exact-active 是 Vue Router 默认给精确匹配路由加的类。
   只用 exact-active 而不是 active,避免 "/" 在所有页面都高亮(因为
   "/" 是所有路径的前缀,会被 router-link-active 误判)。 */
.nav-link.router-link-exact-active {
  @apply bg-blue-50 text-blue-700 font-medium;
}
.nav-link {
  white-space: nowrap;
}
/* 移动端 nav 横向滚:隐藏丑陋的滚动条但仍可拖 */
.nav-scroll {
  scrollbar-width: none;
}
.nav-scroll::-webkit-scrollbar {
  display: none;
}
</style>
