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
        <div class="tile-actions">
          <n-button size="small" type="primary" ghost @click="openEdit(v)">编辑</n-button>
          <n-button v-if="!v.tags_confirmed" size="small" secondary @click="confirmTags(v)">确认标签</n-button>
          <span v-else class="action-spacer" />
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
          <div class="form-item full" v-if="editing.correctedText !== null || editing.transcriptText">
            <label class="form-label">转写 / 校对稿</label>
            <div v-if="editing.transcriptText" class="prose panel" style="margin-bottom: 8px; background: var(--bg)">
              <strong class="muted">ASR 转写（只读）</strong>
              <p style="white-space: pre-wrap">{{ editing.transcriptText }}</p>
            </div>
            <n-input
              v-model:value="editing.correctedText"
              type="textarea"
              :rows="6"
              placeholder="AI 校对稿，可直接修改（分析以此为准）"
            />
          </div>
        </div>
        <div class="row">
          <n-button type="primary" @click="saveEdit">保存</n-button>
          <n-button secondary @click="closeEdit">取消</n-button>
        </div>
      </div>
    </n-modal>
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
const orig = ref(null)
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

async function openEdit(v) {
  let detail = v
  try {
    detail = await api('/api/videos/' + v.id)
  } catch {
    /* 列表数据已够用 */
  }
  const tr = detail.transcript
  editing.value = {
    ...v,
    platforms: [...(v.platforms || [])],
    main_topics: [...(v.main_topics || [])],
    coverUrl: v.cover_url || null,
    sourceText: tr?.source_text || '',
    transcriptText: tr?.transcript_text || '',
    correctedText: tr ? (tr.corrected_text ?? '') : null,
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
    correctedText: editing.value.correctedText
  }
  showEdit.value = true
}

function closeEdit() {
  showEdit.value = false
  editing.value = null
  orig.value = null
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
  if (editing.value.correctedText !== o.correctedText) body.corrected_text = editing.value.correctedText || null
  try {
    await api('/api/videos/' + editing.value.id, { method: 'PATCH', body: JSON.stringify(body) })
    message.success('已保存')
    closeEdit()
    load()
  } catch (e) {
    message.error(e.message)
  }
}

async function confirmTags(v) {
  await api(`/api/videos/${v.id}/confirm-tags`, { method: 'POST', body: JSON.stringify({ tags_confirmed: true }) })
  message.success('标签已确认')
  load()
}

onMounted(async () => {
  await load()
  const m = location.hash.match(/edit=(\d+)/)
  if (m) {
    const v = videos.value.find(x => x.id === Number(m[1]))
    if (v) openEdit(v)
  }
})
</script>
