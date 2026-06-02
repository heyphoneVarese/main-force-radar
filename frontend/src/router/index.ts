// 前端路由(Phase 2:Dashboard 瘦身 + 拆 /continuity /trends)。
//
// History mode:URL 干净,但需要 nginx SPA fallback(已在 frontend/nginx.conf
// 的 `try_files $uri $uri/ /index.html` 配上了);本机 dev 走 vite 自带的
// fallback。
//
// 路由表(Phase 2):
//   /             → Dashboard.vue   (Top10 inflow + outflow + 我的持仓提醒)
//   /continuity   → Continuity.vue  (连续流入 + 连续流出 排行)
//   /trends       → Trends.vue      (板块 20 日资金趋势 + sparkline)
//   /holdings     → Holdings.vue    (持仓 CRUD + 4 张分析卡)
//   /settings     → Settings.vue
//
// Radar.vue 是历史占位文件,从未挂路由,本 PR 也不动它。

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import Continuity from '../views/Continuity.vue'
import Dashboard from '../views/Dashboard.vue'
import Holdings from '../views/Holdings.vue'
import Settings from '../views/Settings.vue'
import Trends from '../views/Trends.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: Dashboard, meta: { label: 'Dashboard' } },
  { path: '/continuity', name: 'continuity', component: Continuity, meta: { label: 'Continuity' } },
  { path: '/trends', name: 'trends', component: Trends, meta: { label: 'Trends' } },
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
