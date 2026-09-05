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
            :key="e.key"
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
          <span class="src">{{ platformName(it.platform, '综合') }}</span>
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
import { fetchVideos, fetchWorks } from '../composables/media'
import { buildTimelineModel } from '../lib/timeline'
import { platformName } from '../lib/format'

const videos = ref([])
const hotItems = ref([])
const refreshing = ref(false)
const generatingTitle = ref(null)
const ideas = ref([])
const ideaBatch = ref(0)
const generatingIdea = ref(0)
const cloudPosts = ref([])
const boundLocalIds = ref(null)
const gaps = ref([])
const angleShow = ref(false)
const angleLoading = ref(false)
const angles = ref([])
const pendingTopic = ref('')

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
const message = useMessage()

const model = computed(() => buildTimelineModel(videos.value, cloudPosts.value, { boundLocalIds: boundLocalIds.value }))

async function loadVideos() {
  videos.value = await fetchVideos()
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
    await api('/api/drafts/generate-async', { method: 'POST', body: JSON.stringify({ topic: title }) })
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
    // 已转本地 → 打开本地素材编辑；否则去素材库打开这条云端作品（不再跳到博主页）
    if (e.local_video_id) location.hash = `#/videos?edit=${e.local_video_id}`
    else location.hash = `#/videos?post=${e.id}`
    return
  }
  goVideo(e.id)
}

function worksToTimelinePosts(works) {
  const label = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
  const one = (p) => label[p.platform] || p.platform || ''
  const out = []
  for (const w of works || []) {
    const posts = w.posts || []
    if (!posts.length) continue
    // 合并作品取“最先发布”的平台时间作为时间线日期（跨平台同作品只展示一条）
    const timed = posts.filter(x => x.publish_time).sort((a, b) => (a.publish_time < b.publish_time ? -1 : 1))
    const first = timed[0] || posts[0]
    const bound = posts.find(x => x.local_video_id)
    const plats = w.platforms && w.platforms.length ? w.platforms : posts.map(x => x.platform)
    const isBench = posts.some(x => x.creator_kind === 'benchmark')
    out.push({
      id: first.id,               // 数字平台帖 id → 素材库 post= 深链
      key: (w.type === 'work' ? 'w' : 'p') + w.id,
      platform: plats[0] || '',
      creator_kind: isBench ? 'benchmark' : 'owner',
      title: w.title || '',
      cover: w.cover || first.cover || '',
      publish_time: first.publish_time || '',
      local_video_id: bound ? bound.local_video_id : null,
      srcLabel: isBench ? (one(first) + '·对标') : plats.map(one).filter(Boolean).join('/')
    })
  }
  return out
}

async function loadCloud() {
  try {
    const data = await fetchWorks()  // 用“合并后作品”，时间线不重复
    const ids = new Set()
    for (const w of data) for (const p of w.posts || []) if (p.local_video_id) ids.add(p.local_video_id)
    boundLocalIds.value = ids
    cloudPosts.value = worksToTimelinePosts(data)
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
