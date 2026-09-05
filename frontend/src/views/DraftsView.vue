<template>
  <div class="page">
    <h1 class="page-title">脚本工作台</h1>

    <div class="toolbar">
      <n-button type="primary" @click="createDraft">新建草稿</n-button>
    </div>

    <n-tabs v-model:value="listTab" type="line" animated>
      <n-tab-pane name="draft" :tab="`草稿 (${list('draft').length})`">
        <div v-if="!list('draft').length" class="panel empty">暂无草稿，新建或从热点生成</div>
        <div class="grid">
          <div v-for="d in list('draft')" :key="d.id" class="card-tile" @click="open(d)">
            <h3 class="tile-title">{{ d.title || '（无标题）' }}</h3>
            <p class="tile-meta">{{ d.source === 'ai' ? 'AI 生成' : '手动' }} · {{ fmt(d.updated_at) }}</p>
            <div class="tile-actions" @click.stop>
              <n-button size="small" secondary @click="markUsed(d)">✅ 采用</n-button>
              <n-button size="small" secondary @click="markArchived(d)">不采用</n-button>
              <n-button size="small" quaternary type="error" @click="softDelete(d)">删除</n-button>
            </div>
            <div class="tile-rate" @click.stop>
              <span class="muted">打分</span>
              <button v-for="i in 5" :key="i" class="rate-star" :class="{ on: (ratings[d.id] || 0) >= i }" @click="rate(d, i)">{{ (ratings[d.id] || 0) >= i ? '★' : '☆' }}</button>
              <span v-if="ratings[d.id]" class="muted" style="font-size: 11px">{{ ratings[d.id] }} 分</span>
            </div>
            <div class="tile-rate dims" @click.stop>
              <span class="muted">分节</span>
              <template v-for="def in dimDefs" :key="def.key">
                <span class="dim-label">{{ def.label }}</span>
                <button
                  v-for="opt in dimOpts"
                  :key="def.key + opt.v"
                  class="rate-star dim-star"
                  :class="{ on: (dims[d.id] || {})[def.key] === opt.v }"
                  @click="setDim(d.id, def.key, opt.v)"
                >{{ opt.label }}</button>
              </template>
              <n-button size="tiny" secondary @click="submitDims(d)">记反馈</n-button>
            </div>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="used" :tab="`待制作 (${list('used').length})`">
        <div v-if="!list('used').length" class="panel empty">暂无待制作（点草稿的「采用」会进这里）</div>
        <div class="grid">
          <div v-for="d in list('used')" :key="d.id" class="card-tile" @click="open(d)">
            <h3 class="tile-title">{{ d.title || '（无标题）' }}</h3>
            <p class="tile-meta">{{ d.source === 'ai' ? 'AI 生成' : '手动' }} · {{ fmt(d.updated_at) }}</p>
            <div class="tile-actions" @click.stop>
              <n-button size="small" secondary @click="markArchived(d)">移入废稿</n-button>
              <n-button size="small" quaternary type="error" @click="softDelete(d)">删除</n-button>
            </div>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="archived" :tab="`废稿/已删除 (${list('archived').length})`">
        <div v-if="!list('archived').length" class="panel empty">废稿箱是空的</div>
        <div class="grid">
          <div v-for="d in list('archived')" :key="d.id" class="card-tile" @click="open(d)">
            <h3 class="tile-title">{{ d.title || '（无标题）' }}</h3>
            <p class="tile-meta">{{ d.source === 'ai' ? 'AI 生成' : '手动' }} · {{ fmt(d.updated_at) }}</p>
            <div class="tile-actions" @click.stop>
              <n-tag v-if="d.status === 'deleted'" size="small" :bordered="false" round type="error">已删除</n-tag>
              <n-button size="small" secondary @click="restore(d)">恢复为草稿</n-button>
              <n-button v-if="d.status !== 'deleted'" size="small" quaternary type="error" @click="softDelete(d)">删除</n-button>
            </div>
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      :title="editing ? (editing.id ? '草稿 #' + editing.id : '新建草稿') : '草稿'"
      style="width: min(860px, 95vw)"
      :mask-closable="false"
      @close="closeEdit"
    >
      <div v-if="editing" style="max-height: 76vh; overflow-y: auto; padding-right: 6px">
        <div class="form-grid" style="margin-bottom: 8px">
          <div class="form-item">
            <label class="form-label">标题</label>
            <n-input v-model:value="editing.title" placeholder="视频标题" />
          </div>
          <div class="form-item">
            <label class="form-label">封面字</label>
            <n-input v-model:value="editing.cover_text" placeholder="与标题不同，3-8 字" />
          </div>
        </div>
        <div class="form-item" style="margin-bottom: 10px">
          <label class="form-label">关联素材视频（可选）</label>
          <n-select v-model:value="editing.video_id" :options="videoOptions" placeholder="选择一个素材视频" clearable />
        </div>

        <n-tabs v-model:value="editTab" type="line" animated>
          <n-tab-pane name="edit" tab="编辑">
            <div class="form-item">
              <label class="form-label">口播脚本（Markdown，可插图）</label>
              <div class="md-toolbar">
                <n-button size="tiny" secondary @click="wrap('**', '**', '加粗文字')"><b>B</b></n-button>
                <n-button size="tiny" secondary @click="wrap('*', '*', '斜体文字')"><i>I</i></n-button>
                <n-button size="tiny" secondary @click="linePrefix('## ')">H2</n-button>
                <n-button size="tiny" secondary @click="linePrefix('> ')">引用</n-button>
                <n-button size="tiny" secondary @click="linePrefix('- ')">列表</n-button>
                <n-button size="tiny" secondary @click="insertHr">分隔线</n-button>
                <n-button size="tiny" secondary @click="insertLink">链接</n-button>
                <n-button size="tiny" secondary @click="imgInput && imgInput.click()">🖼 插图</n-button>
                <input ref="imgInput" type="file" accept="image/*" class="file-hidden" @change="onImage" />
                <span class="grow" />
                <n-button size="tiny" :type="preview ? 'primary' : 'default'" @click="preview = !preview">
                  {{ preview ? '返回编辑' : '预览' }}
                </n-button>
              </div>
              <n-input
                v-if="!preview"
                ref="scriptInput"
                v-model:value="editing.script"
                type="textarea"
                :rows="15"
                placeholder="在这里撰写 / 改写脚本"
              />
              <div v-else class="prose md-preview" v-html="renderMd(editing.script)" />
            </div>
            <div v-if="checkInfo && editing.id" class="panel check-panel" style="margin-bottom: 10px">
              <div class="row" style="gap: 8px; align-items: center">
                <span class="section-title" style="margin: 0">脚本体检</span>
                <n-tag v-if="checkInfo.ok" size="small" type="success" :bordered="false" round>通过</n-tag>
                <n-tag v-else size="small" type="warning" :bordered="false" round>建议回炉</n-tag>
                <div class="grow" />
                <n-button v-if="!checkInfo.ok && editing.id" size="tiny" type="primary" secondary :loading="reworking" @click="rework(editing.id)">一键回炉重写</n-button>
                <n-button size="tiny" secondary @click="runCheck(editing.id)">重新体检</n-button>
              </div>
              <ul v-if="checkInfo.issues.length" style="margin: 6px 0 0; padding-left: 1.2em; color: var(--warn)">
                <li v-for="(iss, i) in checkInfo.issues" :key="i">{{ iss }}</li>
              </ul>
            </div>
            <div class="row">
              <n-button type="primary" @click="save">保存</n-button>
              <n-button secondary @click="closeEdit">取消</n-button>
            </div>
          </n-tab-pane>

          <n-tab-pane name="discuss" tab="讨论（双模型留痕）">
            <div class="discuss-box">
              <div v-if="!discussions.length" class="empty" style="padding: 30px 0">
                暂无讨论记录{{ isPending ? '（生成中…）' : '' }}
              </div>
              <div v-for="m in discussions" :key="m.id" class="discuss-msg" :class="m.actor">
                <div class="discuss-head">
                  <strong>{{ actorName(m) }}</strong>
                  <span class="muted">{{ kindName(m.kind) }} · 第{{ m.round }}轮</span>
                </div>
                <div class="discuss-body" style="white-space: pre-wrap">{{ m.content }}</div>
              </div>
              <div v-if="debateStatus" class="empty" style="padding: 12px 0; color: var(--warn)">⏳ {{ debateStatus }}</div>
              <div v-else-if="isPending" class="empty" style="padding: 12px 0">模型讨论中…</div>
            </div>
          </n-tab-pane>
        </n-tabs>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useMessage } from 'naive-ui'
import { api, uploadImage } from '../api'
import { fetchVideos } from '../composables/media'
import { fmt } from '../lib/format'
import { renderMd } from '../md'

const drafts = ref([])
const videos = ref([])
const videoOptions = computed(() => videos.value.map(v => ({ label: v.title || v.filename, value: v.id })))
const listTab = ref('draft')
const editing = ref(null)
const showEdit = ref(false)
const checkInfo = ref(null)
const reworking = ref(false)
const editTab = ref('edit')
const discussions = ref([])
const discussionsMap = ref({})
const debateStatus = ref('')
const preview = ref(false)
const scriptInput = ref(null)
const imgInput = ref(null)
const ratings = ref({})
const dimDefs = [
  { key: 'hook_score', label: '钩子' },
  { key: 'pace_score', label: '节奏' },
  { key: 'ending_score', label: '结尾' },
  { key: 'style_score', label: '像我' }
]
const dimOpts = [
  { v: 5, label: '好' },
  { v: 3, label: '中' },
  { v: 1, label: '差' }
]
const dims = ref({})
const message = useMessage()
let pollTimer = null

const isPending = computed(() => (editing.value?.script || '').includes('双模型讨论生成中'))

function list(status) {
  if (status === 'archived') {
    return drafts.value.filter(d => d.status === 'archived' || d.status === 'deleted')
  }
  return drafts.value.filter(d => d.status === status)
}
function discussionCount(id) {
  return (discussionsMap.value[id] || []).length
}
function actorName(m) {
  if (m.actor === 'kimi') return 'Kimi'
  if (m.actor === 'deepseek') return 'DeepSeek'
  if (m.actor === 'system') return '系统'
  return m.actor
}
function kindName(k) {
  return { draft: '初稿', critique: '评审', revise: '修订', note: '说明' }[k] || k
}
function textarea() {
  const inp = scriptInput.value
  if (!inp) return null
  return inp.textareaEl || (inp.$el && inp.$el.querySelector('textarea'))
}

async function load() {
  const [ds, vs] = await Promise.all([
    api('/api/drafts?limit=500'),
    fetchVideos()
  ])
  drafts.value = ds
  videos.value = vs
  const counts = await Promise.all(
    drafts.value.map(d => api(`/api/drafts/${d.id}/discussions`).catch(() => []))
  )
  discussionsMap.value = {}
  drafts.value.forEach((d, i) => {
    discussionsMap.value[d.id] = counts[i] || []
  })
}

async function loadDiscussions(id) {
  const rows = await api(`/api/drafts/${id}/discussions`)
  discussions.value = rows
  discussionsMap.value = { ...discussionsMap.value, [id]: rows }
  await fetchStatus(id)
}
async function fetchStatus(id) {
  try {
    const r = await api(`/api/drafts/${id}/debate-status`)
    debateStatus.value = r.status || ''
  } catch {
    debateStatus.value = ''
  }
}

async function createDraft() {
  const d = await api('/api/drafts', { method: 'POST', body: JSON.stringify({ title: '', cover_text: '', script: '' }) })
  open(d, true)
}

function open(d, isNew = false) {
  editing.value = { ...d, video_id: d.video_id ?? null }
  preview.value = false
  showEdit.value = true
  discussions.value = discussionsMap.value[d.id] || []
  if (!isNew && editing.value.id) location.hash = `#/drafts?id=${editing.value.id}`
  if (editing.value.id) runCheck(editing.value.id)
}

function openDiscussion(d) {
  editing.value = { ...d, video_id: d.video_id ?? null }
  showEdit.value = true
  editTab.value = 'discuss'
  discussions.value = discussionsMap.value[d.id] || []
  loadDiscussions(d.id)
}

async function runCheck(id) {
  if (!id) return
  try {
    checkInfo.value = await api(`/api/drafts/${id}/check`)
  } catch (e) {
    checkInfo.value = null
  }
}

async function rework(id) {
  if (!id) return
  reworking.value = true
  try {
    const r = await api(`/api/drafts/${id}/rework`, { method: 'POST', body: '{}' })
    message.success('已提交回炉生成，完成后右上角通知（将替换本稿）')
  } catch (e) {
    message.error(e.message)
  } finally {
    reworking.value = false
  }
}

function closeEdit() {
  showEdit.value = false
  editing.value = null
  debateStatus.value = ''
  checkInfo.value = null
}

async function setStatus(id, status) {
  await api(`/api/drafts/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
}
async function markUsed(d) {
  await setStatus(d.id, 'used')
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: true }) })
  message.success('已采用 → 待制作')
  load()
}
async function markArchived(d) {
  await setStatus(d.id, 'archived')
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: false }) })
  message.success('已移入废稿')
  load()
}
async function restore(d) {
  await setStatus(d.id, 'draft')
  message.success('已恢复为草稿')
  load()
}

async function softDelete(d) {
  await setStatus(d.id, 'deleted')
  message.success('已删除（逻辑删除，可在废稿/已删除中恢复）')
  load()
}

function wrap(prefix, suffix, placeholder) {
  const el = textarea()
  if (!el) return
  const value = editing.value.script
  const s = el.selectionStart
  const e = el.selectionEnd
  const sel = value.slice(s, e) || placeholder
  editing.value.script = value.slice(0, s) + prefix + sel + suffix + value.slice(e)
  nextTick(() => {
    el.focus()
    el.setSelectionRange(s + prefix.length, s + prefix.length + sel.length)
  })
}
function linePrefix(prefix) {
  const el = textarea()
  if (!el) return
  const value = editing.value.script
  const s = el.selectionStart
  const lineStart = value.lastIndexOf('\n', s - 1) + 1
  editing.value.script = value.slice(0, lineStart) + prefix + value.slice(lineStart)
  nextTick(() => {
    el.focus()
    el.setSelectionRange(lineStart + prefix.length, lineStart + prefix.length)
  })
}
function insertHr() {
  const el = textarea()
  if (!el) return
  const value = editing.value.script
  const s = el.selectionStart
  editing.value.script = value.slice(0, s) + '\n---\n' + value.slice(s)
  nextTick(() => el.focus())
}
function insertLink() {
  wrap('[', '](https://)', '链接文字')
}
async function onImage(e) {
  const f = e.target.files[0]
  if (!f) return
  try {
    const r = await uploadImage(f)
    const el = textarea()
    if (el) {
      const value = editing.value.script
      const s = el.selectionStart
      const ins = `\n![图片](${r.url})\n`
      editing.value.script = value.slice(0, s) + ins + value.slice(s)
      nextTick(() => el.focus())
    } else {
      editing.value.script += `\n![图片](${r.url})\n`
    }
    message.success('图片已插入')
  } catch (err) {
    message.error(err.message)
  } finally {
    if (imgInput.value) imgInput.value.value = ''
  }
}

async function save() {
  const body = {
    title: editing.value.title,
    cover_text: editing.value.cover_text,
    script: editing.value.script,
    video_id: editing.value.video_id ?? null
  }
  await api(`/api/drafts/${editing.value.id}`, { method: 'PATCH', body: JSON.stringify(body) })
  message.success('已保存')
  closeEdit()
  load()
}

async function rate(d, i) {
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: null, rating: i }) })
  ratings.value = { ...ratings.value, [d.id]: i }
  message.success(`已打 ${i} 分（进入人设/选题学习）`)
}

function setDim(id, key, v) {
  const cur = dims.value[id] || {}
  dims.value = { ...dims.value, [id]: { ...cur, [key]: cur[key] === v ? null : v } }
}

async function submitDims(d) {
  const sel = dims.value[d.id] || {}
  const body = { liked: null, comment: '' }
  let has = false
  for (const def of dimDefs) {
    if (sel[def.key] != null) {
      body[def.key] = sel[def.key]
      has = true
    }
  }
  if (!has) {
    message.warning('先点选至少一个维度')
    return
  }
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify(body) })
  dims.value = { ...dims.value, [d.id]: {} }
  message.success('分节反馈已记录（会精确回传人设学习）')
}

async function poll() {
  if (!showEdit.value || !editing.value?.id) return
  const id = editing.value.id
  try {
    const rows = await api(`/api/drafts/${id}/discussions`)
    discussionsMap.value = { ...discussionsMap.value, [id]: rows }
    if (editTab.value === 'discuss') discussions.value = rows
    await fetchStatus(id)
  } catch {
    /* ignore */
  }
}

onMounted(async () => {
  await load()
  const m = location.hash.match(/id=(\d+)/)
  if (m) {
    const d = drafts.value.find(x => x.id === Number(m[1]))
    if (d) {
      open(d)
      listTab.value = d.status || 'draft'
    }
  }
  pollTimer = setInterval(poll, 3000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
