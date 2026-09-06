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
      <span class="muted" style="font-size: 13px">评论与热榜按人设相关度均衡展示 · 人工挑选，不自动推送</span>
      <div class="grow" />
      <n-button-group size="small" style="margin-right: 8px">
        <n-button :type="sourceTab === 'all' ? 'primary' : 'default'" @click="sourceTab = 'all'">全部</n-button>
        <n-button :type="sourceTab === 'comment' ? 'primary' : 'default'" @click="sourceTab = 'comment'">只看评论</n-button>
        <n-button :type="sourceTab === 'hot' ? 'primary' : 'default'" @click="sourceTab = 'hot'">只看热榜</n-button>
      </n-button-group>
      <n-button v-if="totalIdeas" size="tiny" secondary @click="rotateIdeas">换一批</n-button>
      <n-button size="tiny" secondary :loading="refreshing" @click="refreshIdeas">抓取更新</n-button>
    </div>
    <div class="panel">
      <div v-if="!totalIdeas" class="empty">暂无灵感（点「抓取更新」或等每日自动同步）</div>
      <div v-else class="idea-list">
        <div v-for="it in shownIdeas" :key="it.id" class="idea-row">
          <span class="src">{{ platformName(it.platform, '综合') }}</span>
          <span class="kind">{{ it.source === 'hot' ? '热榜' : '评论' }}</span>
          <span v-if="it.source === 'hot' && !it.matched" class="low">低相关</span>
          <span v-else-if="it.matched && (it.source === 'comment' || (it.score || 0) > 0)" class="rel">相关</span>
          <span v-if="it.source === 'comment' && it.likes" class="likes">👍 {{ fmtNum(it.likes) }}</span>
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
import { platformName, fmtNum } from '../lib/format'

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
const sourceTab = ref('all')  // all | hot | comment

function withHot() {
  return hotItems.value.map(h => ({
    id: 'hot-' + (h.platform || '') + '-' + h.title,
    platform: h.platform || 'hot',
    title: h.title,
    heat: h.heat || '',
    source: 'hot',
    score: h.score || 0,
    matched: h.matched !== false
  }))
}
function withComments() {
  return ideas.value.map(it => ({
    id: 'idea-' + it.id,
    platform: it.platform || '',
    title: it.title,
    likes: it.likes || 0,
    source: 'comment',
    score: it.score || 0,
    matched: it.matched !== false
  }))
}
// 相关优先（稳定排序：同分保持接口顺序——评论已按点赞降序）
function related(list) {
  const arr = [...list]
  return arr.sort((a, b) => (b.score || 0) - (a.score || 0))
}
function sliceBatch(list) {
  if (!list.length) return []
  const size = Math.min(8, list.length)
  const start = (ideaBatch.value * 8) % list.length
  const out = []
  for (let i = 0; i < size; i++) out.push(list[(start + i) % list.length])
  return out
}
// 「全部」= 评论/热榜各半交替，避免热榜把评论淹没
function mixed(listA, listB) {
  const a = [...listA]
  const b = [...listB]
  const out = []
  const total = 8
  for (let i = 0; i < total; i++) {
    if (i % 2 === 0 && a.length) out.push(a.shift())
    else if (b.length) out.push(b.shift())
    else if (a.length) out.push(a.shift())
  }
  return out
}

const shownIdeas = computed(() => {
  const hot = withHot()
  const comments = withComments()
  if (sourceTab.value === 'hot') return sliceBatch(related(hot))
  if (sourceTab.value === 'comment') return sliceBatch(related(comments))
  const cs = related(comments)
  const hs = related(hot)
  // 换一批：从不同起点开始取半批
  const step = Math.max(1, Math.ceil(4 / Math.max(1, Math.max(cs.length, hs.length))))
  const rot = ideaBatch.value * step
  const ca = []
  const ha = []
  if (cs.length) for (let i = 0; i < 4; i++) ca.push(cs[(rot + i) % cs.length])
  if (hs.length) for (let i = 0; i < 4; i++) ha.push(hs[(rot + i) % hs.length])
  return mixed(ca, ha)
})

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
.kind {
  flex: none;
  font-size: 11px;
  color: #6f675c;
  background: #efebe3;
  padding: 1px 6px;
  border-radius: 8px;
}
.rel {
  flex: none;
  font-size: 11px;
  color: #2f7d4d;
}
.low {
  flex: none;
  font-size: 11px;
  color: #b26a3d;
}
.likes {
  flex: none;
  font-size: 11px;
  color: #a34f2c;
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
