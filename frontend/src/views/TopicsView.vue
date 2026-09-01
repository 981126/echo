<template>
  <div>
    <h1 class="page-title">每日选题</h1>
    <div class="card row">
      <button :disabled="running" @click="runPipeline">{{ running ? '运行中…' : '运行今日流水线' }}</button>
      <button class="secondary" @click="refreshHot">刷新热点</button>
      <span class="muted grow">自动：抓热点 → 匹配 → 生成脚本 → 邮件推送（{{ status.run_date || '—' }} · {{ statusLabel }}）</span>
    </div>
    <div v-if="msg" class="msg" :class="msgType">{{ msg }}</div>
    <div v-if="hot.total" class="card">
      <h3>今日热点（{{ hot.total }} 条）</h3>
      <p class="muted">{{ hot.items.map(h => `[${h.platform}] ${h.title}`).join('；') }}</p>
    </div>
    <div class="card">
      <h3>匹配选题</h3>
      <div v-if="!items.length" class="empty">今日还没有选题，点"运行今日流水线"生成</div>
      <div v-for="c in items" :key="c.id" class="row" style="margin-bottom: 10px">
        <div class="grow">
          <strong>{{ c.title }}</strong>
          <span class="badge">{{ c.platform || '综合' }}</span>
          <span class="badge ok">匹配 {{ c.score }}</span>
          <p class="muted" style="margin: 2px 0">{{ c.reason }}</p>
        </div>
        <a v-if="c.draft_id" class="btn sm" :href="'#/drafts?id=' + c.draft_id">草稿 #{{ c.draft_id }}</a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'

const items = ref([])
const hot = ref({ items: [], total: 0 })
const status = ref({})
const running = ref(false)
const msg = ref('')
const msgType = ref('ok')

const statusLabel = computed(() => {
  const map = { never: '从未运行', running: '运行中', done: '已完成', failed: '失败' }
  return map[status.value.status] || status.value.status
})

async function load() {
  const [c, h, s] = await Promise.all([
    api('/api/topics'),
    api('/api/topics/hot'),
    api('/api/pipeline/status')
  ])
  items.value = c.items
  hot.value = h
  status.value = s
}

async function runPipeline() {
  running.value = true
  try {
    const r = await api('/api/pipeline/run', { method: 'POST', body: '{}' })
    show(`流水线已启动（task #${r.task_id}），稍后刷新查看结果`, 'ok')
    setTimeout(load, 3000)
  } catch (e) { show(e.message, 'err') } finally { running.value = false }
}

async function refreshHot() {
  try {
    const r = await api('/api/topics/refresh', { method: 'POST', body: '{}' })
    show(`热点抓取完成（${r.fetched} 条）`, 'ok')
    load()
  } catch (e) { show(e.message, 'err') }
}

function show(text, type) { msg.value = text; msgType.value = type }

onMounted(load)
</script>
