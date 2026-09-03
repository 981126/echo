<template>
  <n-config-provider :theme-overrides="themeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
        <div class="app-shell">
          <aside v-if="!isLogin" class="sidebar">
            <div class="side-brand">ECHO</div>
            <nav class="side-nav">
              <RouterLink v-for="item in navs" :key="item.to" :to="item.to" @click="menuOpen = false">
                {{ item.label }}
              </RouterLink>
            </nav>
          </aside>

          <div class="workspace">
            <header v-if="!isLogin" class="topbar">
              <RouterLink to="/home" class="top-brand">ECHO</RouterLink>
              <button class="menu-btn" aria-label="菜单" @click="menuOpen = !menuOpen">☰</button>
            </header>
            <main class="main">
              <RouterView />
            </main>
          </div>

          <NotificationBell v-if="!isLogin" />

          <transition name="sheet">
            <div v-if="menuOpen" class="sheet-scrim" @click="menuOpen = false">
              <div class="sheet" @click.stop>
                <RouterLink
                  v-for="item in navs"
                  :key="item.to"
                  :to="item.to"
                  @click="menuOpen = false"
                >
                  {{ item.label }}
                </RouterLink>
              </div>
            </div>
          </transition>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { zhCN, dateZhCN } from 'naive-ui'
import NotificationBell from './components/NotificationBell.vue'

const route = useRoute()
const menuOpen = ref(false)
const isLogin = computed(() => route.path === '/login')

const navs = [
  { to: '/home', label: '主页' },
  { to: '/videos', label: '素材库' },
  { to: '/drafts', label: '脚本工作台' },
  { to: '/chat', label: 'AI 对话' },
  { to: '/persona', label: '人设档案' },
  { to: '/dashboard', label: '数据看板' },
  { to: '/requirements', label: '需求管理' }
]

const themeOverrides = {
  common: {
    primaryColor: '#a34f2c',
    primaryColorHover: '#b7603a',
    primaryColorPressed: '#8a3f1f',
    primaryColorSuppl: '#a34f2c',
    borderRadius: '8px',
    fontSize: '14px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    textColorBase: '#2b2823'
  },
  Button: { fontWeight: '500' },
  Card: { borderRadius: '10px' }
}
</script>
