<template>
  <div class="app-shell">
    <nav v-if="!isLogin" class="sidebar">
      <div class="logo">echo · 回声</div>
      <RouterLink to="/videos">素材库</RouterLink>
      <RouterLink to="/timeline">时间线</RouterLink>
      <RouterLink to="/drafts">脚本工作台</RouterLink>
      <RouterLink to="/chat">AI 对话</RouterLink>
      <RouterLink to="/persona">人设档案</RouterLink>
      <RouterLink to="/requirements">需求管理</RouterLink>
      <RouterLink to="/dashboard">看板</RouterLink>
    </nav>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isLogin = computed(() => route.path === '/login')
</script>
