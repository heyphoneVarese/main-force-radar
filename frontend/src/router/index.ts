// 前端路由(Phase 5.1 PR6)。
//
// History mode:URL 干净,但需要 nginx SPA fallback(已在 frontend/nginx.conf
// 的 `try_files $uri $uri/ /index.html` 配上了);本机 dev 走 vite 自带的
// fallback。
//
// 路由表:
//   /            → Dashboard.vue   (PR7 接真实 API,目前占位)
//   /holdings    → Holdings.vue    (现有 CRUD,业务不动)
//   /settings    → Settings.vue    (占位)
//
// Radar.vue 是 Phase 2 阶段的遗留占位文件,不在路由表里(将来 Dashboard
// 上线后可以删,本 PR 不动它,只暴露 3 个用户实际能进的页面)。

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import Dashboard from '../views/Dashboard.vue'
import Holdings from '../views/Holdings.vue'
import Settings from '../views/Settings.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: Dashboard, meta: { label: 'Dashboard' } },
  { path: '/holdings', name: 'holdings', component: Holdings, meta: { label: 'Holdings' } },
  { path: '/settings', name: 'settings', component: Settings, meta: { label: 'Settings' } },
  // 任何未知路径都回 Dashboard(R4 单用户系统不需要 404 体验)
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
