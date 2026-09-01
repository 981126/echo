<template>
  <div>
    <h1 class="page-title">人设档案</h1>
    <div class="card row">
      <button class="secondary" :disabled="running" @click="initPersona">{{ running ? '初始化中…' : '用历史转写稿初始化人设' }}</button>
      <span class="muted">AI 建议会进入"待确认"，确认后才生效</span>
    </div>
    <div v-if="msg" class="msg" :class="msgType">{{ msg }}</div>

    <div class="card">
      <h3>待确认建议</h3>
      <div v-if="!suggested.length" class="empty">暂无待确认建议</div>
      <div v-for="t in suggested" :key="t.id" class="row" style="margin-bottom: 8px">
        <div class="grow">
          <strong>{{ t.label }}</strong> <span class="badge">{{ t.category }}</span>
          <p class="muted" style="margin: 2px 0">{{ t.description }}</p>
        </div>
        <button class="sm" @click="decide(t, 'confirmed')">确认</button>
        <button class="sm secondary" @click="decide(t, 'rejected')">拒绝</button>
      </div>
    </div>

    <div class="card">
      <h3>已确认档案</h3>
      <div v-if="!confirmed.length" class="empty">暂无已确认人设</div>
      <div v-for="t in confirmed" :key="t.id" class="row" style="margin-bottom: 6px">
        <div class="grow">
          <strong>{{ t.label }}</strong> <span class="badge">{{ t.category }}</span>
          <span class="muted"> · {{ t.description }}</span>
        </div>
        <span v-if="t.category === 'redline'" class="badge ad">红线</span>
      </div>
    </div>

    <div class="card">
      <h3>手动添加</h3>
      <div class="row">
        <label class="field">标签<input v-model="form.label" placeholder="如：犀利敢说" /></label>
        <label class="field">描述<input v-model="form.description" placeholder="一句话描述" /></label>
        <label class="field">类别
          <select v-model="form.category"><option value="style">风格</option><option value="topic">赛道</option><option value="redline">红线</option></select>
        </label>
      </div>
      <button @click="addTag">添加</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const suggested = ref([])
const confirmed = ref([])
const running = ref(false)
const msg = ref('')
const msgType = ref('ok')
const form = ref({ label: '', description: '', category: 'style' })

async function load() {
  const [s, c] = await Promise.all([
    api('/api/persona?status=suggested'),
    api('/api/persona?status=confirmed')
  ])
  suggested.value = s
  confirmed.value = c
}

async function initPersona() {
  running.value = true
  try {
    const r = await api('/api/persona/init', { method: 'POST', body: '{}' })
    show(`初始化任务已启动（task #${r.task_id}），可在"素材库"稍后查看`, 'ok')
  } catch (e) { show(e.message, 'err') } finally { running.value = false }
}

async function decide(t, status) {
  await api(`/api/persona/tags/${t.id}/decision`, { method: 'POST', body: JSON.stringify({ status }) })
  load()
}

async function addTag() {
  if (!form.value.label.trim()) { show('请填写标签', 'err'); return }
  await api('/api/persona/tags', { method: 'POST', body: JSON.stringify(form.value) })
  form.value = { label: '', description: '', category: 'style' }
  load()
}

function show(text, type) { msg.value = text; msgType.value = type }

onMounted(load)
</script>
