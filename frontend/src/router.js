import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from './api'

const routes = [
  { path: '/login', component: () => import('./views/LoginView.vue') },
  { path: '/', redirect: '/home' },
  { path: '/home', component: () => import('./views/HomeView.vue'), meta: { title: '主页' } },
  { path: '/videos', component: () => import('./views/VideosView.vue'), meta: { title: '素材库' } },
  { path: '/drafts', component: () => import('./views/DraftsView.vue'), meta: { title: '脚本工作台' } },
  { path: '/chat', component: () => import('./views/ChatView.vue'), meta: { title: 'AI 对话' } },
  { path: '/persona', component: () => import('./views/PersonaView.vue'), meta: { title: '人设档案' } },
  { path: '/prompts', component: () => import('./views/PromptsView.vue'), meta: { title: 'AI 设置' } },
  { path: '/benchmark', component: () => import('./views/BenchmarkView.vue'), meta: { title: '博主对标' } },
  { path: '/creators', component: () => import('./views/CreatorsView.vue'), meta: { title: '博主管理' } }
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
