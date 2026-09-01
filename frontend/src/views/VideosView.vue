<template>
  <div>
    <h1 class="page-title">素材库</h1>
    <div class="card row">
      <input type="file" accept="video/*" @change="onFile" />
      <button :disabled="uploading" @click="doUpload">{{ uploading ? '上传中…' : '上传视频' }}</button>
      <span class="muted grow">或直接把视频拖到 NAS 的 data/inbox 文件夹，系统自动入库</span>
    </div>
    <div v-if="msg" class="msg" :class="msgType">{{ msg }}</div>
    <div class="card row">
      <select v-model="filter.platform"><option value="">平台：全部</option><option value="douyin">抖音</option><option value="bilibili">B站</option><option value="xiaohongshu">小红书</option></select>
      <select v-model="filter.status"><option value="">状态：全部</option><option value="planned">计划中</option><option value="published">已发布</option></select>
      <select v-model="filter.main_topic"><option value="">赛道：全部</option><option v-for="t in topics" :key="t" :value="t">{{ t }}</option></select>
      <button class="secondary" @click="load">查询</button>
    </div>
    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="!videos.length" class="empty">暂无视频，先上传或投放到 inbox</div>
    <div class="grid">
      <div v-for="v in videos" :key="v.id" class="card">
        <div class="row">
          <strong class="grow">{{ v.filename }}</strong>
          <span v-if="v.is_ad" class="badge ad">广告</span>
          <span class="badge">{{ v.platform || '未定' }}</span>
        </div>
        <p class="muted">赛道：{{ v.main_topic || '未标' }} · 状态：{{ v.status === 'published' ? '已发布' : '计划中' }}</p>
        <p class="muted">
          <span v-if="v.planned_publish_at">计划：{{ fmt(v.planned_publish_at) }}</span>
          <span v-if="v.published_at"> · 发布：{{ fmt(v.published_at) }}</span>
        </p>
        <p>
          <span v-for="t in v.tags" :key="t" class="badge">{{ t }}</span>
          <span v-if="!v.tags.length" class="muted">无标签</span>
        </p>
        <div class="row">
          <button class="sm secondary" @click="openEdit(v)">编辑</button>
          <button v-if="!v.tags_confirmed" class="sm" @click="confirmTags(v)">确认标签</button>
        </div>
      </div>
    </div>

    <div v-if="editing" class="card">
      <h3>编辑：{{ editing.filename }}</h3>
      <div class="row">
        <label class="field">平台
          <select v-model="editing.platform"><option value="">未定</option><option value="douyin">抖音</option><option value="bilibili">B站</option><option value="xiaohongshu">小红书</option></select>
        </label>
        <label class="field">主赛道
          <select v-model="editing.main_topic"><option value="">未标</option><option v-for="t in topics" :key="t" :value="t">{{ t }}</option></select>
        </label>
        <label class="field">状态
          <select v-model="editing.status"><option value="planned">计划中</option><option value="published">已发布</option></select>
        </label>
      </div>
      <div class="row">
        <label class="field">计划发布时间
          <input type="datetime-local" v-model="editing.planned_publish_at" />
        </label>
        <label class="field">实际发布时间
          <input type="datetime-local" v-model="editing.published_at" />
        </label>
      </div>
      <label class="field"><input type="checkbox" v-model="editing.is_ad" /> 商务广告（不参与人设学习）</label>
      <label class="field">标签（逗号分隔）
        <input v-model="tagsText" placeholder="干货, 反常识, 口播" />
      </label>
      <label class="field">原始文案（可选，仅供参考）
        <textarea v-model="editing.source_text" style="min-height: 80px"></textarea>
      </label>
      <div class="row">
        <button @click="saveEdit">保存</button>
        <button class="secondary" @click="editing = null">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api, uploadVideo } from '../api'

const topics = ['求职', '面试', '赚钱', '知识', '其他']
const videos = ref([])
const filter = ref({ platform: '', status: '', main_topic: '' })
const loading = ref(false)
const uploading = ref(false)
const file = ref(null)
const msg = ref('')
const msgType = ref('ok')
const editing = ref(null)
const tagsText = ref('')

function fmt(v) { return v ? v.replace('T', ' ').slice(0, 16) : '' }

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    Object.entries(filter.value).forEach(([k, v]) => { if (v) params.set(k, v) })
    params.set('limit', '500')
    const data = await api('/api/videos?' + params.toString())
    videos.value = data.items
  } catch (e) { show(e.message, 'err') } finally { loading.value = false }
}

function onFile(e) { file.value = e.target.files[0] || null }

async function doUpload() {
  if (!file.value) { show('请先选择视频文件', 'err'); return }
  uploading.value = true
  try {
    await uploadVideo(file.value)
    show('上传成功，已触发转写', 'ok')
    file.value = null
    load()
  } catch (e) { show(e.message, 'err') } finally { uploading.value = false }
}

function openEdit(v) {
  editing.value = { ...v, source_text: '', planned_publish_at: toLocal(v.planned_publish_at), published_at: toLocal(v.published_at) }
  tagsText.value = (v.tags || []).join(', ')
}

function toLocal(v) { return v ? v.replace(' ', 'T').slice(0, 16) : '' }

async function saveEdit() {
  try {
    const body = { ...editing.value }
    delete body.id; delete body.filename; delete body.created_at; delete body.tags; delete body.tags_confirmed; delete body.transcript
    body.tags = tagsText.value.split(/[,，]/).map(s => s.trim()).filter(Boolean)
    const saved = await api('/api/videos/' + editing.value.id, { method: 'PATCH', body: JSON.stringify(body) })
    show('已保存', 'ok')
    editing.value = null
    load()
  } catch (e) { show(e.message, 'err') }
}

async function confirmTags(v) {
  try {
    await api(`/api/videos/${v.id}/confirm-tags`, { method: 'POST', body: JSON.stringify({ tags_confirmed: true }) })
    show('标签已确认', 'ok')
    load()
  } catch (e) { show(e.message, 'err') }
}

function show(text, type) { msg.value = text; msgType.value = type }

onMounted(load)
</script>
