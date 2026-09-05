<template>
  <div class="page">
    <h1 class="page-title">素材库</h1>

    <div class="panel row">
      <input ref="fileInput" type="file" accept="video/*" class="file-hidden" @change="onFile" />
      <n-button secondary @click="fileInput && fileInput.click()">选择视频文件</n-button>
      <span v-if="file" class="muted grow">{{ file.name }}</span>
      <span v-else class="muted grow">或拖入 data/inbox 自动入库</span>
      <n-button type="primary" :disabled="!file" :loading="uploading" @click="doUpload">
        {{ uploading ? '上传中…' : '上传' }}
      </n-button>
    </div>

    <div class="toolbar">
      <n-select v-model:value="filter.platform" :options="platformOptions" placeholder="平台" clearable style="width: 130px" />
      <n-select v-model:value="filter.status" :options="statusOptions" placeholder="状态" clearable style="width: 130px" />
      <n-select v-model:value="filter.main_topic" :options="topicOptions" placeholder="赛道" clearable style="width: 130px" />
      <n-button secondary @click="load">查询</n-button>
    </div>

    <div v-if="loading" class="panel empty">加载中…</div>
    <div v-else-if="!videos.length" class="panel empty">暂无视频</div>
    <div v-else class="grid grid-videos">
      <div v-for="v in videos" :key="v.id" class="card-tile">
        <div class="tile-cover" :class="{ has: v.cover_url }" @click="openEdit(v)">
          <img v-if="v.cover_url" :src="v.cover_url" alt="封面" />
          <span v-else>ECHO</span>
        </div>
        <h3 class="tile-title" style="word-break: break-all" @click="openEdit(v)">{{ v.title || v.filename }}</h3>
        <div class="row" style="gap: 6px">
          <n-tag v-if="v.is_ad" size="small" :bordered="false" round type="error">广告</n-tag>
          <n-tag v-for="p in v.platforms" :key="p" size="small" :bordered="false" round>{{ platformName(p) }}</n-tag>
          <n-tag v-for="t in v.main_topics" :key="t" size="small" :bordered="false" round type="info">{{ t }}</n-tag>
        </div>
        <p class="tile-meta" style="word-break: break-all; margin-top: 8px">{{ v.filename }}</p>
        <p class="tile-meta" style="margin-top: -2px">
          {{ v.status === 'published' ? '已发布' : '计划中' }}
          <template v-if="v.planned_publish_at"> · 计划 {{ fmt(v.planned_publish_at) }}</template>
          <template v-if="v.published_at"> · 发布 {{ fmt(v.published_at) }}</template>
        </p>
        <div class="row" style="gap: 5px; margin-bottom: 6px">
          <n-tag v-for="t in v.tags" :key="t" size="small" :bordered="false">{{ t }}</n-tag>
          <span v-if="!v.tags.length" class="muted">无标签</span>
        </div>
        <div class="row" style="gap: 6px; margin-top: 6px">
          <n-tag v-if="v.platform_post_id" size="tiny" type="success" :bordered="false" round>已绑定作品</n-tag>
          <n-button
            v-if="v.platform_post_id"
            size="tiny"
            secondary
            :loading="syncing === v.id"
            @click="syncData(v)"
          >同步数据</n-button>
        </div>
        <div v-if="!v.tags_confirmed" class="tile-actions">
          <n-button size="small" secondary @click="confirmTags(v)">确认标签</n-button>
        </div>
      </div>
    </div>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      :title="editing ? '编辑：' + editing.filename : '编辑视频'"
      style="width: min(760px, 94vw)"
      :mask-closable="false"
      @close="closeEdit"
    >
      <div v-if="editing" style="max-height: 72vh; overflow-y: auto; padding-right: 6px">
        <div class="form-item">
          <label class="form-label">标题</label>
          <n-input v-model:value="editing.title" placeholder="视频标题（选题标题）" />
        </div>
        <div class="form-item">
          <label class="form-label">发布链接（可选，用于“同步数据”）</label>
          <n-input v-model:value="editing.publishLink" placeholder="粘贴抖音 /video/、B站 /video/BV、小红书 /explore/ 作品链接" />
        </div>
        <div class="row" style="gap: 18px; align-items: flex-start; margin-bottom: 14px">
          <div class="cover-edit" @click="coverInput && coverInput.click()">
            <img v-if="editing.coverUrl" :src="editing.coverUrl" alt="封面" />
            <span v-else>上传封面</span>
          </div>
          <input ref="coverInput" type="file" accept="image/jpeg,image/png" class="file-hidden" @change="onCover" />
          <div class="grow muted" style="font-size: 12px">
            <div style="margin-top: 4px">jpg / png，点击图片上传或替换</div>
            <n-button v-if="editing.coverUrl" size="tiny" quaternary type="error" style="margin-top: 8px" @click="removeCover">
              移除封面
            </n-button>
          </div>
        </div>

        <div v-if="linkedDrafts.length" class="form-item">
          <label class="form-label">已关联脚本（点击打开）</label>
          <div class="row" style="gap: 6px">
            <n-button
              v-for="d in linkedDrafts"
              :key="d.id"
              size="tiny"
              secondary
              @click="goDraft(d.id)"
            >#{{ d.id }} {{ d.title || '（无标题）' }}</n-button>
          </div>
        </div>

        <div class="form-grid">
          <div class="form-item">
            <label class="form-label">平台（可多选）</label>
            <n-select v-model:value="editing.platforms" multiple :options="platformOptions" placeholder="选择平台" />
          </div>
          <div class="form-item">
            <label class="form-label">赛道（可多选）</label>
            <n-select v-model:value="editing.main_topics" multiple :options="topicOptions" placeholder="选择赛道" />
          </div>
          <div class="form-item">
            <label class="form-label">状态</label>
            <n-select v-model:value="editing.status" :options="statusOptions" />
          </div>
          <div class="form-item">
            <label class="form-label">商务广告</label>
            <n-checkbox v-model:checked="editing.is_ad">广告（不参与人设学习）</n-checkbox>
          </div>
          <div class="form-item">
            <label class="form-label">计划发布时间</label>
            <n-date-picker v-model:value="editing.plannedTs" type="datetime" clearable style="width: 100%" />
          </div>
          <div class="form-item">
            <label class="form-label">实际发布时间</label>
            <n-date-picker v-model:value="editing.publishedTs" type="datetime" clearable style="width: 100%" />
          </div>
          <div class="form-item full">
            <label class="form-label">标签（逗号分隔）</label>
            <n-input v-model:value="tagsText" placeholder="干货, 反常识, 口播" />
          </div>
          <div class="form-item full">
            <label class="form-label">原始文案（可选）</label>
            <n-input v-model:value="editing.sourceText" type="textarea" :rows="3" placeholder="与口播可能不一致" />
          </div>
          <div class="form-item full" v-if="editing.transcriptText">
            <label class="form-label">ASR 转写（只读）</label>
            <div class="prose panel" style="margin-bottom: 0; background: var(--bg)">
              <p style="white-space: pre-wrap">{{ editing.transcriptText }}</p>
            </div>
          </div>
        </div>
        <div class="row">
          <n-button type="primary" @click="saveEdit">保存</n-button>
          <n-button secondary @click="closeEdit">取消</n-button>
        </div>
      </div>

    </n-modal>
    <div class="section-title" style="margin-top: 28px">
      云端作品
      <span class="muted" style="font-size: 12px">同一内容发三个平台会自动合并成一条，不重复展示</span>
      <div class="grow"></div>
      <n-button v-if="!mergeMode" size="tiny" secondary @click="mergeMode = true">选择合并</n-button>
      <template v-else>
        <n-button size="tiny" type="primary" :disabled="selected.size < 2" @click="doMerge">合并所选（{{ selected.size }}）</n-button>
        <n-button size="tiny" secondary @click="cancelMerge">取消</n-button>
      </template>
    </div>
    <div class="panel">
      <div v-if="worksLoading" class="empty">加载中…</div>
      <div v-else-if="!works.length" class="empty">暂无云端作品（先在「博主」页同步平台数据）</div>
      <div v-else class="work-grid">
        <div v-for="w in works" :key="(w.type === 'work' ? 'w' : 'p') + w.id" class="work-card" :class="{ sel: selected.has(w.id) }">
          <div class="work-cover" @click="openWorkDetail(w)">
            <img v-if="w.cover" :src="w.cover" alt="" />
            <span v-else>ECHO</span>
            <n-checkbox v-if="mergeMode && w.type === 'post'" class="work-sel" :checked="selected.has(w.id)" @update:checked="toggleSel(w)" />
          </div>
          <div class="work-body">
            <div class="work-title" :title="w.title">{{ w.title }}</div>
            <div class="row" style="gap: 4px; margin-top: 6px; flex-wrap: wrap">
              <n-tag v-for="pl in w.platforms" :key="pl" size="tiny" :bordered="false" round>{{ platformName(pl) }}</n-tag>
              <n-tag v-if="w.type === 'work'" size="tiny" type="info" :bordered="false">合并×{{ w.posts.length }}</n-tag>
            </div>
            <div v-for="pst in w.posts" :key="pst.id" class="plat-line">
              <b>{{ platformName(pst.platform) }}</b>
              <template v-if="pst.latest_stat">
                <span>播放 {{ fmtNum(pst.latest_stat.plays) }}</span>
                <span>赞 {{ fmtNum(pst.latest_stat.likes) }}</span>
                <span v-if="pst.latest_stat.comments">评 {{ fmtNum(pst.latest_stat.comments) }}</span>
              </template>
              <span v-else class="muted">暂无指标</span>
            </div>
            <div class="row" style="gap: 5px; flex-wrap: wrap; margin-top: 8px">
              <n-button v-for="pst in w.posts" :key="'s' + pst.id" size="tiny" secondary :loading="syncingPost === pst.id" @click="syncCloudPost(pst)">同步{{ platformName(pst.platform) }}</n-button>
              <n-button v-if="w.type === 'work'" size="tiny" quaternary type="error" @click="splitWork(w)">拆分</n-button>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api, uploadVideo, uploadCover } from '../api'

const message = useMessage()
const topics = ['求职', '面试', '赚钱', '知识', '其他']
const videos = ref([])
const filter = ref({ platform: null, status: null, main_topic: null })
const loading = ref(false)
const uploading = ref(false)
const file = ref(null)
const fileInput = ref(null)
const coverInput = ref(null)
const editing = ref(null)
const linkedDrafts = ref([])
const orig = ref(null)
const syncing = ref(0)
const works = ref([])
const worksLoading = ref(false)
const mergeMode = ref(false)
const selected = ref(new Set())
const syncingPost = ref(0)
const showEdit = ref(false)
const tagsText = ref('')

const platformOptions = [
  { label: '抖音', value: 'douyin' },
  { label: 'B站', value: 'bilibili' },
  { label: '小红书', value: 'xiaohongshu' }
]
const statusOptions = [
  { label: '计划中', value: 'planned' },
  { label: '已发布', value: 'published' }
]
const topicOptions = topics.map(t => ({ label: t, value: t }))
const PLATFORM_NAMES = { douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' }
const platformName = (p) => PLATFORM_NAMES[p] || p || ''

function fmt(v) {
  return v ? v.replace('T', ' ').slice(0, 16) : ''
}

function parseTs(v) {
  if (!v) return null
  const d = new Date(String(v).replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? null : d.getTime()
}

function tsLocal(ts) {
  if (!ts) return null
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function arrKey(arr) {
  return JSON.stringify([...(arr || [])].sort())
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    Object.entries(filter.value).forEach(([k, v]) => {
      if (v) params.set(k, v)
    })
    params.set('limit', '500')
    const data = await api('/api/videos?' + params.toString())
    videos.value = data.items
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function onFile(e) {
  file.value = e.target.files[0] || null
}

async function doUpload() {
  if (!file.value) {
    message.warning('请先选择视频文件')
    return
  }
  uploading.value = true
  try {
    await uploadVideo(file.value)
    message.success('上传成功，已触发转写')
    file.value = null
    if (fileInput.value) fileInput.value.value = ''
    load()
  } catch (e) {
    message.error(e.message)
  } finally {
    uploading.value = false
  }
}

async function onCover(e) {
  const f = e.target.files[0]
  if (!f || !editing.value) return
  try {
    await uploadCover(editing.value.id, f)
    message.success('封面已更新')
    closeEdit()
    load()
  } catch (err) {
    message.error(err.message)
  } finally {
    if (coverInput.value) coverInput.value.value = ''
  }
}

async function removeCover() {
  try {
    await api(`/api/videos/${editing.value.id}/cover`, { method: 'DELETE' })
    message.success('封面已移除')
    closeEdit()
    load()
  } catch (e) {
    message.error(e.message)
  }
}

function goDraft(id) {
  showEdit.value = false
  editing.value = null
  location.hash = `#/drafts?id=${id}`
}

async function openEdit(v) {
  let detail = v
  try {
    detail = await api('/api/videos/' + v.id)
  } catch {
    /* 列表数据已够用 */
  }
  try {
    linkedDrafts.value = await api(`/api/drafts?video_id=${v.id}&limit=20`)
  } catch {
    linkedDrafts.value = []
  }
  const tr = detail.transcript
  editing.value = {
    ...v,
    platforms: [...(v.platforms || [])],
    main_topics: [...(v.main_topics || [])],
    coverUrl: v.cover_url || null,
    publishLink: v.platform_post_id || '',
    sourceText: tr?.source_text || '',
    transcriptText: tr?.transcript_text || '',
    plannedTs: parseTs(v.planned_publish_at),
    publishedTs: parseTs(v.published_at)
  }
  tagsText.value = (v.tags || []).join(', ')
  orig.value = {
    title: editing.value.title,
    platforms: [...editing.value.platforms],
    main_topics: [...editing.value.main_topics],
    status: editing.value.status,
    is_ad: editing.value.is_ad,
    plannedTs: editing.value.plannedTs,
    publishedTs: editing.value.publishedTs,
    tagsText: tagsText.value,
    sourceText: editing.value.sourceText,
    publishLink: editing.value.publishLink
  }
  showEdit.value = true
}

function closeEdit() {
  showEdit.value = false
  editing.value = null
  orig.value = null
  linkedDrafts.value = []
}

async function saveEdit() {
  const o = orig.value
  if (!o) return
  const body = {}
  if ((editing.value.title || '') !== (o.title || '')) body.title = editing.value.title || ''
  if (arrKey(editing.value.platforms) !== arrKey(o.platforms)) body.platforms = editing.value.platforms || []
  if (arrKey(editing.value.main_topics) !== arrKey(o.main_topics)) body.main_topics = editing.value.main_topics || []
  if (editing.value.status !== o.status) body.status = editing.value.status
  if (editing.value.is_ad !== o.is_ad) body.is_ad = editing.value.is_ad
  if ((editing.value.plannedTs || null) !== o.plannedTs) body.planned_publish_at = tsLocal(editing.value.plannedTs)
  if ((editing.value.publishedTs || null) !== o.publishedTs) body.published_at = tsLocal(editing.value.publishedTs)
  if (tagsText.value !== o.tagsText) {
    body.tags = tagsText.value.split(/[,，]/).map(s => s.trim()).filter(Boolean)
  }
  if (editing.value.sourceText !== o.sourceText) body.source_text = editing.value.sourceText || null
  const linkChanged = (editing.value.publishLink || '') !== (o.publishLink || '')
  try {
    await api('/api/videos/' + editing.value.id, { method: 'PATCH', body: JSON.stringify(body) })
    if (linkChanged && editing.value.publishLink) {
      try {
        await api(`/api/platform/videos/${editing.value.id}/bind-link`, { method: 'POST', body: JSON.stringify({ link: editing.value.publishLink }) })
        message.success('发布链接已绑定，可同步数据')
      } catch (e) {
        message.warning('保存成功，但发布链接解析失败：' + e.message)
      }
    }
    message.success('已保存')
    closeEdit()
    load()
  } catch (e) {
    message.error(e.message)
  }
}

function fmtNum(n) {
  n = Number(n || 0)
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return String(n)
}

async function loadWorks() {
  worksLoading.value = true
  try {
    const data = await api('/api/works')
    works.value = data.items || []
  } catch (e) {
    works.value = []
  } finally {
    worksLoading.value = false
  }
}

function openWorkDetail(w) {
  message.info('同一作品：' + (w.platforms || []).map(platformName).join(' / '))
}

function toggleSel(w) {
  const next = new Set(selected.value)
  if (next.has(w.id)) next.delete(w.id)
  else next.add(w.id)
  selected.value = next
}

function cancelMerge() {
  mergeMode.value = false
  selected.value = new Set()
}

async function doMerge() {
  const ids = [...selected.value]
  if (ids.length < 2) return
  try {
    await api('/api/works/merge', { method: 'POST', body: JSON.stringify({ platform_post_ids: ids }) })
    message.success('已合并为同一作品')
    cancelMerge()
    loadWorks()
  } catch (e) {
    message.error(e.message)
  }
}

async function splitWork(w) {
  try {
    await api(`/api/works/${w.id}/split`, { method: 'POST', body: JSON.stringify({ platform_post_ids: [] }) })
    message.success('已拆分')
    loadWorks()
  } catch (e) {
    message.error(e.message)
  }
}

async function syncCloudPost(pst) {
  syncingPost.value = pst.id
  try {
    await api(`/api/platform/posts/${pst.id}/sync`, { method: 'POST' })
    message.success('已同步 ' + platformName(pst.platform))
    loadWorks()
  } catch (e) {
    message.error(e.message)
  } finally {
    syncingPost.value = 0
  }
}

async function syncData(v) {
  syncing.value = v.id
  try {
    const r = await api(`/api/platform/videos/${v.id}/sync`, { method: 'POST' })
    message.success(r.message || '同步完成')
  } catch (e) {
    message.error(e.message)
  } finally {
    syncing.value = 0
  }
}

async function confirmTags(v) {
  await api(`/api/videos/${v.id}/confirm-tags`, { method: 'POST', body: JSON.stringify({ tags_confirmed: true }) })
  message.success('标签已确认')
  load()
}

onMounted(async () => {
  await load()
  await loadWorks()
  const m = location.hash.match(/edit=(\d+)/)
  if (m) {
    const v = videos.value.find(x => x.id === Number(m[1]))
    if (v) openEdit(v)
  }
})
</script>

<style scoped>
.work-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
@media (max-width: 1100px) { .work-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 820px) { .work-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .work-grid { grid-template-columns: 1fr; } }
.work-card {
  background: #fffdfa;
  border: 1px solid #eee5d8;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.work-card.sel { border-color: #a34f2c88; }
.work-cover {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #efe6d9;
  color: #a34f2c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  cursor: pointer;
  overflow: hidden;
}
.work-cover img { width: 100%; height: 100%; object-fit: cover; }
.work-sel { position: absolute; top: 6px; left: 6px; }
.work-body { padding: 8px 10px 10px; min-width: 0; }
.work-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  font-size: 14px;
}
.plat-line {
  display: flex;
  gap: 6px;
  font-size: 11px;
  color: #6f675c;
  margin-top: 4px;
  flex-wrap: wrap;
  overflow: hidden;
}
.plat-line b { color: #a34f2c; }
.plat-stat b {
  color: #a34f2c;
}

</style>
