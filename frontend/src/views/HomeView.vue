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
            @click="goEvent(e)"
          >
            <img v-if="e.coverUrl" class="tl-cover" :src="e.coverUrl" loading="lazy" alt="" @click.stop="goEvent(e)" />
            <span v-else class="tl-cover empty">ECHO</span>
            <span class="dot" />
            <span class="nm">{{ e.title }}</span>
            <span v-if="e.srcLabel" class="tl-src">{{ e.srcLabel }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="section-title" style="margin-top: 28px">
      灵感池
      <span class="muted" style="font-size: 13px">各平台热榜 + 评论均衡混排 · 人工挑选，不自动推送</span>
      <div class="grow" />
      <n-button v-if="totalIdeas" size="tiny" secondary @click="rotateIdeas">换一批</n-button>
      <n-button size="tiny" secondary :loading="refreshing" @click="refreshIdeas">抓取更新</n-button>
    </div>
    <div class="panel">
      <div v-if="!totalIdeas" class="empty">暂无灵感（点「抓取更新」或等每日自动同步）</div>
      <div v-else class="idea-list">
        <div v-for="it in shownIdeas" :key="it.id" class="idea-row">
          <span class="src">{{ platformName(it.platform) }}</span>
          <span class="kind">{{ it.source === 'hot' ? '热榜' : '评论' }}</span>
          <span class="grow ellipsis" style="min-width: 0">{{ it.title }}</span>
          <n-button size="tiny" type="primary" secondary :loading="generatingIdea === it.id" @click="pickAngle(it.title)">生成文案</n-button>
        </div>
      </div>
    </div>

<n-modal v-model:show="angleShow" preset="card" title="选一个切入角度" style="width: min(680px, 94vw)">
    <div v-if="angleLoading" class="panel empty">正在想 3 个角度…</div>
    <div v-else-if="!angles.length" class="panel empty">暂时没想出来，直接按原话题生成</div>
    <div v-else class="angle-list">
      <div
        v-for="(a, i) in angles"
        :key="i"
        class="angle-card"
        @click="generateWithAngle(a.title)"
      >
        <div class="angle-no">{{ i + 1 }}</div>
        <div>
          <div class="angle-title">{{ a.title }}</div>
          <div v-if="a.hook" class="muted" style="font-size: 12px; margin-top: 4px">钩子：{{ a.hook }}</div>
          <div v-if="a.reason" class="muted" style="font-size: 12px; opacity: .75; margin-top: 2px">{{ a.reason }}</div>
        </div>
        <n-button size="tiny" secondary class="angle-go">用它生成</n-button>
      </div>
    </div>
    <div v-if="!angleLoading" class="row" style="margin-top: 10px">
      <n-button size="small" secondary @click="generateDirect(pendingTopic)">不选角度，直接生成</n-button>
      <n-button size="small" quaternary @click="angleShow = false">取消</n-button>
    </div>
  </n-modal>

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
const ideas = ref([])
const ideaBatch = ref(0)
const generatingIdea = ref(0)
const cloudPosts = ref([])
const gaps = ref([])
const angleShow = ref(false)
const angleLoading = ref(false)
const angles = ref([])
const pendingTopic = ref('')

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

const totalIdeas = computed(() => hotItems.value.length + ideas.value.length)

function unifiedIdeas() {
  const hot = hotItems.value.map(h => ({
    id: 'hot-' + (h.platform || '') + '-' + h.title,
    platform: h.platform || 'hot',
    title: h.title,
    source: 'hot'
  }))
  const comments = ideas.value.map(it => ({ ...it, source: 'comment' }))
  const all = [...hot, ...comments]
  const groups = {}
  all.forEach(it => { (groups[it.platform] = groups[it.platform] || []).push(it) })
  // 平台多的排前，保证混排时每个平台都能轮流出现
  const plats = Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length)
  const per = 8
  const out = []
  const cursor = {}
  plats.forEach((pl, pi) => {
    cursor[pl] = (ideaBatch.value * Math.max(1, Math.ceil(per / Math.max(plats.length, 1))) + pi) % groups[pl].length
  })
  while (out.length < per) {
    let moved = false
    for (const pl of plats) {
      const g = groups[pl]
      if (cursor[pl] >= g.length) continue
      out.push(g[cursor[pl]])
      cursor[pl] += 1
      moved = true
      if (out.length >= per) break
    }
    if (!moved) break
  }
  return out
}

const shownIdeas = computed(() => unifiedIdeas())

function rotateIdeas() {
  ideaBatch.value++
}

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
      kind: 'video',
      date,
      status: v.published_at ? 'published' : 'planned',
      title: (v.title || (v.main_topics && v.main_topics[0]) || v.filename).slice(0, 14),
      fullTitle: v.title || v.filename,
      coverUrl: v.cover_url || '',
      srcLabel: ''
    })
  }
  for (const p of cloudPosts.value) {
    const date = p.publish_time ? p.publish_time.slice(0, 10) : ''
    if (!date) continue
    raw.push({
      id: p.id,
      kind: 'cloud',
      date,
      status: 'published',
      title: (p.title || '').slice(0, 14) || '云端作品',
      fullTitle: p.title || '云端作品',
      coverUrl: p.cover || '',
      srcLabel: p.creator_kind === 'benchmark' ? platformName(p.platform) + '·对标' : platformName(p.platform),
      local_video_id: p.local_video_id
    })
  }
  raw.sort((a, b) => (a.date > b.date ? -1 : 1))  // R-042：倒叙，最新在前（左）
  if (!raw.length) return { events: [], months: [], width: 0, todayLeft: null }

  const dates = raw.map(r => dayNum(r.date))
  const start = Math.min(...dates) - 3
  const end = Math.max(...dates, dayNum(fmtDate(new Date()))) + 6
  const span = Math.max(30, end - start)
  const step = pickStep(span)          // 基础步长：按整体跨度，空档不会被撑开
  const minSep = 94                   // 相邻作品最小像素间距（卡片不叠）

  const months = []
  const s0 = new Date(start * DAY)
  const e0 = new Date(end * DAY)
  for (let d = new Date(Date.UTC(s0.getUTCFullYear(), s0.getUTCMonth(), 1)); d <= e0; d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))) {
    const left = (end - dayNum(fmtDate(d))) * step
    months.push({ key: `${d.getUTCFullYear()}-${d.getUTCMonth()}`, label: `${d.getUTCFullYear()}年${d.getUTCMonth() + 1}月`, left })
  }

  // 同一天多条：以当天为中心水平错开（间距 = minSep）
  const byDate = {}
  raw.forEach(r => { (byDate[r.date] = byDate[r.date] || []).push(r) })
  const items = []
  Object.keys(byDate).sort().forEach((date) => {
    const list = byDate[date]
    const n = list.length
    const baseLeft = (end - dayNum(date)) * step + step / 2
    list.forEach((r, i) => {
      const off = n > 1 ? (i - (n - 1) / 2) * minSep : 0
      items.push({ ...r, left0: baseLeft + off })
    })
  })
  items.sort((a, b) => a.left0 - b.left0)

  // 局部弹性：只有“相邻太近”的才就地向右推开（级联），长空档不放大、不用滑很久
  let prev = -Infinity
  const events = items.map((it) => {
    const left = Math.max(it.left0, prev + minSep)
    prev = left
    return { ...it, left }
  })

  const today = dayNum(fmtDate(new Date()))
  const todayLeft = today >= start && today <= end ? (end - today) * step + step / 2 : null
  const width = Math.max(span * step, (events.length ? Math.max(...events.map(e => e.left)) : 0) + 140)
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
    message.success(`已抓取最新热点（${r.fetched || 0} 条）`)
    await loadHot()
    await loadIdeas()
  } catch (e) {
    message.error('刷新失败：' + e.message)
  } finally {
    refreshing.value = false
  }
}

function refreshIdeas() {
  refreshHot()
}

async function pickAngle(topic) {
  pendingTopic.value = topic
  angleShow.value = true
  angleLoading.value = true
  angles.value = []
  try {
    const r = await api('/api/drafts/angles', { method: 'POST', body: JSON.stringify({ topic }) })
    angles.value = r.angles || []
  } catch (e) {
    angles.value = []
    message.warning('角度生成失败，将按原话题生成：' + e.message)
  } finally {
    angleLoading.value = false
  }
}

async function generateWithAngle(title) {
  angleShow.value = false
  generatingTitle.value = pendingTopic.value
  try {
    const r = await api('/api/drafts/generate-async', { method: 'POST', body: JSON.stringify({ topic: title }) })
    message.success('已提交双模型讨论生成（约 1-2 分钟），完成后右上角通知你')
  } catch (e) {
    message.error('提交失败：' + e.message)
  } finally {
    generatingTitle.value = null
  }
}

async function generateDirect(topic) {
  angleShow.value = false
  generatingTitle.value = topic
  try {
    await api('/api/drafts/generate-async', { method: 'POST', body: JSON.stringify({ topic }) })
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

function goEvent(e) {
  if (e.kind === 'cloud') {
    if (e.local_video_id) location.hash = `#/videos?edit=${e.local_video_id}`
    else location.hash = '#/creators'
    return
  }
  goVideo(e.id)
}

async function loadCloud() {
  try {
    const data = await api('/api/platform/posts?limit=300')
    cloudPosts.value = data.items || []
  } catch (e) {
    /* 静默 */
  }
}

async function loadGaps() {
  try {
    const r = await api('/api/topics/gaps?days=28')
    gaps.value = (r.items || []).filter(g => g.published <= 1 || g.asking_comments > 0).slice(0, 4)
  } catch (e) {
    gaps.value = []
  }
}

async function loadIdeas() {
  try {
    ideaBatch.value = 0
    const data = await api('/api/platform/topic-pool')
    ideas.value = data.items || []
  } catch (e) {
    /* 静默 */
  }
}

async function genFromIdea(it) {
  generatingIdea.value = it.id
  try {
    const r = await api(`/api/platform/topic-pool/${it.id}/generate`, { method: 'POST', body: '{}' })
    if (r.draft && r.draft.id) location.hash = `#/drafts?id=${r.draft.id}`
    else message.success('已生成')
    await loadIdeas()
  } catch (e) {
    message.error('生成失败：' + e.message)
  } finally {
    generatingIdea.value = 0
  }
}

onMounted(() => {
  loadVideos()
  loadHot()
  loadCloud()
  loadIdeas()
  loadGaps()
})
</script>

<style scoped>
.tl-src {
  position: absolute;
  top: 4px;
  right: 2px;
  font-size: 10px;
  color: #a34f2c;
  background: rgba(163, 79, 44, 0.08);
  padding: 0 5px;
  border-radius: 8px;
}
.idea-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.idea-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: #faf7f2;
  border-radius: 8px;
  font-size: 13px;
}
.src {
  flex: none;
  font-size: 11px;
  color: #a34f2c;
  background: rgba(163, 79, 44, 0.1);
  padding: 1px 6px;
  border-radius: 8px;
}

.angle-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.angle-card {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  background: #faf7f2;
  border: 1px solid #eee5d8;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color .15s;
}
.angle-card:hover {
  border-color: #a34f2c88;
}
.angle-no {
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #a34f2c;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
.angle-title {
  font-weight: 600;
}
.angle-go {
  margin-left: auto;
  flex: none;
}

.gap-tag {
  display: flex;
  gap: 8px;
  align-items: center;
  background: #faf7f2;
  border: 1px solid #eee5d8;
  border-radius: 20px;
  padding: 6px 14px;
  font-size: 13px;
}
.gap-tag.low {
  border-color: #a34f2c66;
  background: #fdf6ef;
}
.gap-tag .ask {
  color: #a34f2c;
  font-size: 12px;
}
</style>
