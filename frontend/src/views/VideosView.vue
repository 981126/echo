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
      <n-button secondary @click="load">查询</n-button>
      <n-button :type="mergeMode ? 'primary' : 'default'" size="small" secondary @click="mergeMode = !mergeMode">合并</n-button>
    </div>
    <div v-if="mergeMode" class="row" style="gap: 8px; margin: 8px 0">
      <span class="muted">勾选 2 个以上云端素材，合并为同一作品</span>
      <div class="grow" />
      <n-button size="tiny" type="primary" :disabled="selected.size < 2" @click="doMergeCloud">合并所选（{{ selected.size }}）</n-button>
      <n-button size="tiny" secondary @click="cancelMerge">取消</n-button>
    </div>

    <div v-if="loading" class="panel empty">加载中…</div>
    <div v-else-if="!cards.length" class="panel empty">暂无素材（可上传本地视频，或在「博主」页同步云端作品）</div>
    <div v-else class="grid grid-videos">
      <div v-for="it in cards" :key="it.key" class="card-tile" :class="{ picking: mergeMode && it.kind === 'cloud' }" @click="onCardClick(it)">
        <div class="tile-cover" :class="{ has: it.cover_url }" @click.stop="onCardClick(it)">
          <n-checkbox v-if="mergeMode && it.kind === 'cloud'" class="pick-box" :checked="selected.has(it.key)" @click.stop @update:checked="toggleSel(it)" />
          <img v-if="it.cover_url" :src="it.cover_url" alt="封面" />
          <span v-else>ECHO</span>
        </div>
        <div class="row" style="gap: 4px; margin-top: 6px; flex-wrap: wrap">
          <n-tag v-if="it.kind === 'cloud'" size="small" type="info" :bordered="false" round>云端</n-tag>
          <n-tag v-if="it.kind === 'cloud' && it.merged" size="tiny" type="success" :bordered="false" round>合并×{{ it.merged }}</n-tag>
          <n-tag v-if="it.is_ad" size="small" :bordered="false" round type="error">广告</n-tag>
          <n-tag v-for="p in it.platforms" :key="p" size="small" :bordered="false" round>{{ platformName(p) }}</n-tag>
          <n-tag v-for="t in it.main_topics || []" :key="t" size="small" :bordered="false" round type="info">{{ t }}</n-tag>
        </div>
        <h3 class="tile-title" :title="it.title" @click="openItem(it)">{{ it.title }}</h3>

        <template v-if="it.kind === 'local'">
          <p class="tile-meta" style="word-break: break-all; margin-top: 8px">{{ it.filename }}</p>
          <p class="tile-meta" style="margin-top: -2px">
            {{ it.status === 'published' ? '已发布' : '计划中' }}
            <template v-if="it.planned_publish_at"> · 计划 {{ fmt(it.planned_publish_at) }}</template>
            <template v-if="it.published_at"> · 发布 {{ fmt(it.published_at) }}</template>
          </p>
          <div class="row" style="gap: 5px; margin-bottom: 6px">
            <n-tag v-for="t in it.tags" :key="t" size="small" :bordered="false">{{ t }}</n-tag>
            <span v-if="!it.tags.length" class="muted">无标签</span>
          </div>
          <div class="row-actions">
            <n-tag v-if="it.platform_post_id" size="tiny" type="success" :bordered="false" round>已绑定作品</n-tag>
            <n-button v-if="it.platform_post_id" size="small" secondary :loading="syncing === it.id" @click="syncData(it)">同步数据</n-button>
            <n-button v-if="!it.tags_confirmed" size="small" secondary @click="confirmTags(it)">确认标签</n-button>
            <n-button size="small" quaternary type="error" @click="delLocal(it)">删除</n-button>
          </div>
        </template>

        <template v-else>
          <p class="tile-meta" style="margin-top: 6px">
            {{ it.cloudPosts.map(x => platformName(x.platform)).join(' / ') }}
            <template v-if="it.pub"> · {{ it.pub }}</template>
          </p>
          <div v-for="pst in it.cloudPosts.slice(0, 3)" :key="pst.id" class="plat-line">
            <b>{{ platformName(pst.platform) }}</b>
            <template v-if="pst.latest_stat">
              <span>播放 {{ fmtNum(pst.latest_stat.plays) }}</span>
              <span>赞 {{ fmtNum(pst.latest_stat.likes) }}</span>
              <span v-if="pst.latest_stat.comments">评 {{ fmtNum(pst.latest_stat.comments) }}</span>
            </template>
            <span v-else class="muted">暂无指标</span>
          </div>
          <div class="row-actions">
            <n-button size="small" type="primary" secondary @click="openCloud(it)">上传视频/文案</n-button>
            <n-button size="small" secondary :loading="syncingPost === it.cloudPosts[0].id" @click="syncCloudPost(it.cloudPosts[0])">同步数据</n-button>
            <n-button v-if="it.merged >= 2" size="small" quaternary type="warning" @click="splitWork(it)">拆分</n-button>
            <n-button v-if="it.local_video_id" size="small" secondary @click="goLocal(it.local_video_id)">打开本地</n-button>
            <n-button size="small" quaternary type="error" @click="delCloud(it)">删除</n-button>
          </div>
        </template>
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
            <label class="form-label">标签（逗号分隔，自由填写）</label>
            <n-input v-model:value="tagsText" placeholder="干货, 反常识, 口播, 面试, 赚钱" />
            <span class="muted" style="font-size: 12px">命中 求职/面试/赚钱/知识/其他 的词会同时进入数据统计（复盘/缺口用）</span>
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
    <n-modal v-model:show="showCloud" preset="card" :title="'转本地素材：' + (cloudItem && cloudItem.title || '')" style="width: min(620px, 94vw)">
      <div v-if="cloudItem" style="max-height: 70vh; overflow-y: auto; padding-right: 4px">
        <div class="form-item">
          <label class="form-label">上传视频（可选，会触发转写）</label>
          <div class="row" style="gap: 8px">
            <input ref="cloudFileInput" type="file" accept="video/*" class="file-hidden" @change="onCloudFile" />
            <n-button secondary @click="cloudFileInput && cloudFileInput.click()">选择视频文件</n-button>
            <span v-if="cloudFile" class="muted grow">{{ cloudFile.name }}</span>
          </div>
        </div>
        <div class="form-item">
          <label class="form-label">文案 / 原始文字（可选）</label>
          <n-input v-model:value="cloudText" type="textarea" :rows="5" placeholder="粘贴你的口播文案或字幕，转本地素材后可用于 AI 学习" />
        </div>
        <p class="muted" style="font-size: 12px">
          保存后此作品会出现在素材库（云端标识去掉），可继续编辑平台/赛道/发布时间。
        </p>
        <div class="row">
          <n-button type="primary" :loading="cloudSaving" @click="saveCloudLocal">保存为本地素材</n-button>
          <n-button secondary @click="showCloud = false">取消</n-button>
        </div>
      </div>
    </n-modal>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api, uploadVideo, uploadCover, getToken } from '../api'

const message = useMessage()
const dialog = useDialog()
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
const cards = ref([])
const showCloud = ref(false)
const cloudItem = ref(null)
const cloudFile = ref(null)
const cloudText = ref('')
const cloudSaving = ref(false)
const cloudFileInput = ref(null)
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
    buildCards()
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
  const known5 = ['求职', '面试', '赚钱', '知识', '其他']
  const allTags = [...new Set([...(v.main_topics || []), ...(v.tags || [])])]
  tagsText.value = allTags.join(', ')
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
  if (editing.value.status !== o.status) body.status = editing.value.status
  if (editing.value.is_ad !== o.is_ad) body.is_ad = editing.value.is_ad
  if ((editing.value.plannedTs || null) !== o.plannedTs) body.planned_publish_at = tsLocal(editing.value.plannedTs)
  if ((editing.value.publishedTs || null) !== o.publishedTs) body.published_at = tsLocal(editing.value.publishedTs)
  if (tagsText.value !== o.tagsText) {
    const known5 = ['求职', '面试', '赚钱', '知识', '其他']
    const parts = tagsText.value.split(/[,，]/).map(x => x.trim()).filter(Boolean)
    body.main_topics = parts.filter(x => known5.includes(x))
    body.tags = parts.filter(x => !known5.includes(x))
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
    buildCards()
  } catch (e) {
    works.value = []
  } finally {
    worksLoading.value = false
  }
}

function buildCards() {
  // 云端已绑定本地素材(转素材后)的记录不重复展示，避免合并后多个素材
  const linkedLocal = new Set()
  const cloudWorks = works.value || []
  cloudWorks.forEach(w => {
    const wPosts = w.posts || []
    wPosts.forEach(pst => { if (pst.local_video_id) linkedLocal.add(pst.local_video_id) })
  })
  const local = videos.value.filter(v => !linkedLocal.has(v.id)).map(v => ({
    key: 'v' + v.id,
    kind: 'local',
    id: v.id,
    title: v.title || v.filename || '',
    cover_url: v.cover_url || '',
    platforms: v.platforms || [],
    main_topics: v.main_topics || [],
    is_ad: v.is_ad,
    tags: v.tags || [],
    status: v.status,
    planned_publish_at: v.planned_publish_at,
    published_at: v.published_at,
    filename: v.filename,
    tags_confirmed: v.tags_confirmed,
    platform_post_id: v.platform_post_id,
    date: (v.published_at || v.planned_publish_at || v.created_at || '').slice(0, 10)
  }))
  const cloud = (works.value || []).map(w => {
    const anyLocal = (w.posts || []).find(x => x.local_video_id)
    return {
      key: (w.type === 'work' ? 'w' : 'p') + w.id,
      kind: 'cloud',
      id: w.id,
      type: w.type,
      title: w.title || '（无标题）',
      cover_url: w.cover || '',
      platforms: w.platforms || [],
      main_topics: [],
      is_ad: false,
      tags: [],
      merged: w.type === 'work' ? (w.posts || []).length : 0,
      cloudPosts: w.posts || [],
      local_video_id: anyLocal ? anyLocal.local_video_id : null,
      pub: ((w.posts || [])[0] && (w.posts[0].publish_time || '')).slice(0, 10) || '',
      date: (((w.posts || [])[0] && (w.posts[0].publish_time || '')) || '').slice(0, 10)
    }
  })
  cards.value = [...local, ...cloud].sort((a, b) => (b.date < a.date ? -1 : 1))
}

function openItem(it) {
  if (it.kind === 'cloud') {
    if (it.local_video_id) {
      goLocal(it.local_video_id)
      return
    }
    openCloud(it)
  } else openEdit(it)
}

function onCardClick(it) {
  if (mergeMode.value && it.kind === 'cloud') toggleSel(it)
  else openItem(it)
}

function openCloud(it) {
  cloudItem.value = it
  cloudFile.value = null
  cloudText.value = ''
  showCloud.value = true
}

function onCloudFile(e) {
  cloudFile.value = e.target.files[0] || null
}

async function goLocal(id) {
  await load()
  const v = videos.value.find(x => x.id === id)
  if (v) openEdit(v)
}

async function saveCloudLocal() {
  if (!cloudItem.value) return
  cloudSaving.value = true
  try {
    const fd = new FormData()
    if (cloudFile.value) fd.append('file', cloudFile.value)
    if (cloudText.value) fd.append('text', cloudText.value)
    if (cloudItem.value.type === 'work') fd.append('work_id', String(cloudItem.value.id))
    else fd.append('post_id', String(cloudItem.value.id))
    const resp = await fetch('/api/works/to-local', {
      method: 'POST',
      headers: { 'X-Access-Token': getToken() },
      body: fd
    })
    if (!resp.ok) {
      let detail = resp.statusText
      try { detail = (await resp.json()).detail || detail } catch (e) { detail = detail || e.message }
      throw new Error(detail)
    }
    const r = await resp.json()
    message.success(cloudFile.value ? '已保存并触发转写' : '已转为本地素材（可继续编辑）')
    showCloud.value = false
    await load()
    await loadWorks()
    if (r.video_id) {
      const v = videos.value.find(x => x.id === r.video_id)
      if (v) openEdit(v)
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    cloudSaving.value = false
    if (cloudFileInput.value) cloudFileInput.value.value = ''
  }
}

function openWorkDetail(w) {
  message.info('同一作品：' + (w.platforms || []).map(platformName).join(' / '))
}

function toggleSel(w) {
  const key = w.key || w.id
  const next = new Set(selected.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
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

async function doMergeCloud() {
  const keys = [...selected.value]
  const ids = []
  cards.value.forEach(c => {
    if (c.kind === 'cloud' && keys.includes(c.key)) {
      (c.cloudPosts || []).forEach(x => ids.push(x.id))
    }
  })
  const uniq = [...new Set(ids)]
  if (uniq.length < 2) {
    message.warning('请选择至少 2 个云端素材')
    return
  }
  try {
    await api('/api/works/merge', { method: 'POST', body: JSON.stringify({ platform_post_ids: uniq }) })
    message.success('已合并为同一作品')
    cancelMerge()
    await loadWorks()
  } catch (e) {
    message.error(e.message)
  }
}

function delLocal(it) {
  dialog.warning({
    title: '删除素材',
    content: `确定删除「${it.title || it.filename}」？会删除本地记录与文件，不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api(`/api/videos/${it.id}`, { method: 'DELETE' })
        message.success('已删除')
        await load()
        await loadWorks()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
}

function delCloud(it) {
  const kind = it.type === 'work' ? 'work' : 'post'
  dialog.warning({
    title: '删除云端素材',
    content: `确定删除「${it.title}」？会删除该${kind === 'work' ? '合并作品及其所有平台记录' : '平台记录'}。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api(`/api/works/${it.id}?kind=${kind}`, { method: 'DELETE' })
        message.success('已删除')
        await loadWorks()
      } catch (e) {
        message.error(e.message)
      }
    }
  })
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


.card-tile { position: relative; }
.tile-cover { position: relative; }
.card-tile.picking { cursor: pointer; }
.pick-box {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 3;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 6px;
  padding: 2px;
}
.row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 32px;
  margin-top: 8px;
}

.card-tile { display: flex; flex-direction: column; }
.row-actions { margin-top: auto; }
</style>
