<template>
  <div class="login-wrap">
    <div class="login-panel">
      <div class="login-brand">回声<span>ECHO STUDIO</span></div>
      <h1 class="login-title">进入工作台</h1>
      <p class="muted login-hint">输入访问令牌以继续</p>
      <n-input
        v-model:value="token"
        type="password"
        show-password-on="click"
        placeholder="访问令牌"
        size="large"
        @keyup.enter="login"
      />
      <div style="margin-top: 16px">
        <n-button type="primary" size="large" block :disabled="!token.trim()" :loading="loading" @click="login">
          进入
        </n-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { setToken } from '../api'

const token = ref('')
const loading = ref(false)
const router = useRouter()
const message = useMessage()

async function login() {
  loading.value = true
  setToken(token.value.trim())
  try {
    const resp = await fetch('/health')
    if (!resp.ok) throw new Error('无法连接后端')
    router.push('/videos')
  } catch {
    setToken('')
    message.error('无法连接后端服务，请确认已启动 uvicorn')
  } finally {
    loading.value = false
  }
}
</script>
