<template>
  <div style="max-width: 380px; margin: 12vh auto; padding: 0 16px">
    <div class="card">
      <h1 style="margin: 0 0 4px">echo · 回声</h1>
      <p class="muted" style="margin-bottom: 16px">输入访问令牌进入系统</p>
      <label class="field">
        访问令牌
        <input v-model="token" type="password" placeholder="X-Access-Token" @keyup.enter="login" />
      </label>
      <div v-if="err" class="msg err">{{ err }}</div>
      <button style="width: 100%" :disabled="!token" @click="login">进入</button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { setToken } from '../api'

const token = ref('')
const err = ref('')
const router = useRouter()

async function login() {
  err.value = ''
  setToken(token.value.trim())
  try {
    const resp = await fetch('/health')
    if (!resp.ok) throw new Error('无法连接后端')
    router.push('/videos')
  } catch (e) {
    setToken('')
    err.value = '无法连接后端服务，请确认已启动 uvicorn'
  }
}
</script>
