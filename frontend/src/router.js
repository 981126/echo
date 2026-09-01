import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from './api'

const routes = [
  { path: '/login', component: () => import('./views/LoginView.vue') },
  { path: '/', redirect: '/videos' },
  { path: '/videos', component: () => import('./views/VideosView.vue'), meta: { title: '素材库' } },
  { path: '/timeline', component: () => import('./views/TimelineView.vue'), meta: { title: '时间线' } },
  { path: '/drafts', component: () => import('./views/DraftsView.vue'), meta: { title: '脚本工作台' } },
  { path: '/chat', component: () => import('./views/ChatView.vue'), meta: { title: 'AI 对话' } },
  { path: '/persona', component: () => import('./views/PersonaView.vue'), meta: { title: '人设档案' } },
  { path: '/requirements', component: () => import('./views/RequirementsView.vue'), meta: { title: '需求管理' } },
  { path: '/dashboard', component: () => import('./views/DashboardView.vue'), meta: { title: '看板' } }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !getToken()) return '/login'
  return true
})

export default router
