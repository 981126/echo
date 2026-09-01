<template>
  <div>
    <h1 class="page-title">脚本工作台</h1>
    <div class="card row">
      <button @click="createDraft">新建草稿</button>
      <span class="muted grow">在这里直接改写 AI 生成的脚本并保存（AI 原稿会留底，改稿差异会进入人设学习）</span>
    </div>
    <div v-if="msg" class="msg" :class="msgType">{{ msg }}</div>
    <div class="grid">
      <div v-for="d in drafts" :key="d.id" class="card" :class="{ 'msg ok': editing && editing.id === d.id }">
        <strong>{{ d.title || '（无标题）' }}</strong>
        <p class="muted">来源：{{ d.source === 'ai' ? 'AI 生成' : '手动' }} · 更新：{{ fmt(d.updated_at) }} · 状态：{{ d.status }}</p>
        <div class="row">
          <button class="sm" @click="open(d)">编辑</button>
          <button class="sm secondary" @click="like(d, true)">👍 采用</button>
          <button class="sm secondary" @click="like(d, false)">👎 不用</button>
        </div>
      </div>
    </div>

    <div v-if="editing" class="card">
      <div class="row">
        <label class="field grow">标题<input v-model="editing.title" placeholder="视频标题" /></label>
        <label class="field">封面字<input v-model="editing.cover_text" placeholder="与标题不同，3-8 字" /></label>
      </div>
      <label class="field">口播脚本
        <textarea v-model="editing.script" placeholder="在这里撰写/改写脚本"></textarea>
      </label>
      <div class="row">
        <button @click="save">保存</button>
        <button class="secondary" @click="editing = null">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const drafts = ref([])
const editing = ref(null)
const msg = ref('')
const msgType = ref('ok')

function fmt(v) { return v ? v.replace('T', ' ').slice(0, 16) : '' }

async function load() { drafts.value = await api('/api/drafts?limit=100') }

async function createDraft() {
  const d = await api('/api/drafts', { method: 'POST', body: JSON.stringify({ title: '', cover_text: '', script: '' }) })
  open(d)
}

function open(d) {
  editing.value = { ...d }
  if (editing.value.id) location.hash = `#/drafts?id=${editing.value.id}`
}

async function save() {
  const body = { title: editing.value.title, cover_text: editing.value.cover_text, script: editing.value.script }
  await api(`/api/drafts/${editing.value.id}`, { method: 'PATCH', body: JSON.stringify(body) })
  show('已保存（若为 AI 原稿改写，差异已进入人设学习）', 'ok')
  editing.value = null
  load()
}

async function like(d, liked) {
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked }) })
  show(liked ? '已标记采用' : '已标记不用', 'ok')
  load()
}

function show(text, type) { msg.value = text; msgType.value = type }

onMounted(async () => {
  await load()
  const m = location.hash.match(/id=(\d+)/)
  if (m) {
    const d = drafts.value.find(x => x.id === Number(m[1]))
    if (d) open(d)
  }
})
</script>
