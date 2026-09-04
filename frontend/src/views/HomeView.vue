<template>
  <div class="page">
    <div class="section-title" style="margin-top: 4px">时间线</div>
    <div class="panel">
      <div v-if="!model.events.length" class="empty">暂无视频时间记录</div>
      <div v-else class="tl-wrap">
        <div class="tl" :style="{ width: model.width + 'px' }">
          <div class="tl-axis" />
          <div v-if="model.todayLeft !== null" class="tl-today" :style="{ left: model.todayLeft + 'px' }">
            <span class="tl-today-label">今天</span>
          </div>
          <div
            v-for="m in model.months"
            :key="m.key"
            class="tl-month"
            :style="{ left: m.left + 'px' }"
          >
            {{ m.label }}
          </div>
          <div
            v-for="e in model.events"
            :key="e.id"
            class="tl-ev"
            :class="e.status"
            :style="{ left: e.left + 'px' }"
            :title="e.fullTitle + ' · ' + e.date"
            @click="goVideo(e.id)"
          >
            <img v-if="e.coverUrl" class="tl-cover" :src="e.coverUrl" loading="lazy" alt="" @click.stop="goVideo(e.id)" />
            <span v-else class="tl-cover empty">ECHO</span>
            <span class="dot" />
            <span class="nm">{{ e.title }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="toolbar" style="margin-top: 24px">
      <span class="section-title" style="margin: 0">热点选题</span>
      <n-select v-model:value="platFilter" :options="platOptions" placeholder="全部平台" clearable style="width: 140px" @update:value="shuffle" />
      <n-button size="small" secondary @click="shuffle">换一批</n-button>
      <n-button size="small" secondary :loading="refreshing" @click="refreshHot">抓取更新</n-button>
      <span class="muted">共 {{ shownHot.length }} 条</span>
    </div>
    <div class="panel">
      <div v-if="!shownHot.length" class="empty">暂无热点，点「抓取更新」</div>
      <div v-else class="hot-tags">
        <button
          v-for="h in shownHot"
          :key="h.id"
          class="hot-tag"
          :disabled="generatingTitle !== null"
          @click="genFromHot(h)"
        >
          <span class="src">{{ platformName(h.platform) }}</span>
          <span>{{ generatingTitle === h.title ? '生成中…' : h.title }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api } from '../api'

const videos = ref([])
const hotItems = ref([])
const platFilter = ref(null)
const batch = ref(0)
const platOptions = [
  { label: '抖音', value: 'douyin' },
  { label: 'B站', value: 'bilibili' },
  { label: '小红书', value: 'xiaohongshu' }
]
const refreshing = ref(false)
const generatingTitle = ref(null)

const shownHot = computed(() => {
  let list = hotItems.value
  if (platFilter.value) list = list.filter(h => h.platform === platFilter.value)
  const arr = [...list]
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr.slice(0, 15)
})

function shuffle() {
  batch.value++
}
const message = useMessage()

const PLATFORM_NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => PLATFORM_NAMES[p] || p || '综合'
const DAY = 86400000

function dayNum(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number)
  return Date.UTC(y, m - 1, d) / DAY
}

function fmtDate(d) {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
}

function pickStep(spanDays) {
  if (spanDays <= 45) return 26
  if (spanDays <= 120) return 18
  if (spanDays <= 300) return 9
  return 5
}

const model = computed(() => {
  const raw = []
  for (const v of videos.value) {
    const date = v.published_at ? v.published_at.slice(0, 10) : v.planned_publish_at ? v.planned_publish_at.slice(0, 10) : ''
    if (!date) continue
    raw.push({
      id: v.id,
      date,
      status: v.published_at ? 'published' : 'planned',
      title: (v.title || (v.main_topics && v.main_topics[0]) || v.filename).slice(0, 14),
      fullTitle: v.title || v.filename,
      coverUrl: v.cover_url || ''
    })
  }
  raw.sort((a, b) => (a.date < b.date ? -1 : 1))
  if (!raw.length) return { events: [], months: [], width: 0, todayLeft: null }

  const dates = raw.map(r => dayNum(r.date))
  const start = Math.min(...dates) - 7
  const end = Math.max(...dates, dayNum(fmtDate(new Date()))) + 10
  const span = Math.max(30, end - start)
  const step = pickStep(span)
  const width = span * step

  const months = []
  const s = new Date(start * DAY)
  const e = new Date(end * DAY)
  for (let d = new Date(Date.UTC(s.getUTCFullYear(), s.getUTCMonth(), 1)); d <= e; d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))) {
    const left = (dayNum(fmtDate(d)) - start) * step
    months.push({ key: `${d.getUTCFullYear()}-${d.getUTCMonth()}`, label: `${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月`, left })
  }

  const events = raw.map(r => ({
    ...r,
    left: (dayNum(r.date) - start) * step + step / 2
  }))

  const today = dayNum(fmtDate(new Date()))
  const todayLeft = today >= start && today <= end ? (today - start) * step + step / 2 : null
  return { events, months, width, todayLeft }
})

async function loadVideos() {
  const data = await api('/api/videos?limit=500')
  videos.value = data.items
}

async function loadHot() {
  try {
    const h = await api('/api/topics/hot')
    hotItems.value = h.items || []
  } catch (e) {
    message.error(e.message)
  }
}

async function refreshHot() {
  refreshing.value = true
  try {
    const r = await api('/api/topics/refresh', { method: 'POST', body: '{}' })
    message.success(`热点已刷新（${r.fetched || 0} 条）`)
    await loadHot()
  } catch (e) {
    message.error('刷新失败：' + e.message)
  } finally {
    refreshing.value = false
  }
}

async function genFromHot(h) {
  generatingTitle.value = h.title
  try {
    const r = await api('/api/drafts/generate-async', { method: 'POST', body: JSON.stringify({ topic: h.title }) })
    message.success('已提交双模型讨论生成（约 1-2 分钟），完成后右上角通知你')
  } catch (e) {
    message.error('提交失败：' + e.message)
  } finally {
    generatingTitle.value = null
  }
}

function goVideo(id) {
  location.hash = `#/videos?edit=${id}`
}

onMounted(() => {
  loadVideos()
  loadHot()
})
</script>
