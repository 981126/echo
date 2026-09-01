<template>
  <div>
    <h1 class="page-title">AI 对话</h1>
    <div class="card">
      <div class="chat-box" ref="box">
        <div v-if="!messages.length" class="empty">问问我：目前素材库里有哪些视频？人设档案是什么？上周数据如何？</div>
        <div v-for="m in messages" :key="m.id" class="bubble" :class="m.role">{{ m.content }}</div>
        <div v-if="waiting" class="bubble assistant">思考中…</div>
      </div>
    </div>
    <div class="card row">
      <input class="grow" v-model="text" placeholder="输入问题（只读查询直接答；生成/修改请到工作台操作）" @keyup.enter="send" />
      <button :disabled="waiting || !text.trim()" @click="send">发送</button>
    </div>
    <p class="muted">权限边界：对话仅支持只读查询；生成脚本、修改数据等写操作请在对应页面操作。</p>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { api } from '../api'

const messages = ref([])
const text = ref('')
const waiting = ref(false)
const box = ref(null)

async function load() { messages.value = await api('/api/chat/history?limit=50') }

async function send() {
  const q = text.value.trim()
  if (!q || waiting.value) return
  text.value = ''
  waiting.value = true
  messages.value.push({ id: 'tmp', role: 'user', content: q })
  scroll()
  try {
    const r = await api('/api/chat', { method: 'POST', body: JSON.stringify({ message: q }) })
    messages.value.push({ id: r.message_id, role: 'assistant', content: r.reply })
  } catch (e) {
    messages.value.push({ id: 'err', role: 'assistant', content: '出错了：' + e.message })
  } finally {
    waiting.value = false
    scroll()
  }
}

async function scroll() {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
}

onMounted(load)
</script>
