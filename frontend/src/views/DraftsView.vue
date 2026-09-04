<template>
  <div class="page">
    <h1 class="page-title">脚本工作台</h1>

    <div class="toolbar">
      <n-button type="primary" @click="createDraft">新建草稿</n-button>
    </div>

    <div v-if="!drafts.length" class="panel empty">暂无草稿</div>
    <div class="grid">
      <div v-for="d in drafts" :key="d.id" class="card-tile" @click="open(d)">
        <h3 class="tile-title">{{ d.title || '（无标题）' }}</h3>
        <p class="tile-meta">{{ d.source === 'ai' ? 'AI 生成' : '手动' }} · {{ fmt(d.updated_at) }} · {{ statusName(d.status) }}</p>
        <div class="tile-actions" @click.stop>
          <n-button size="small" type="primary" ghost @click="open(d)">编辑</n-button>
          <n-button v-if="discussionCount(d.id)" size="small" secondary @click="openDiscussion(d)">讨论</n-button>
          <n-button size="small" secondary @click="like(d, true)">👍 采用</n-button>
          <n-button size="small" secondary @click="like(d, false)">👎 不用</n-button>
        </div>
        <div class="tile-rate" @click.stop>
          <span class="muted">打分</span>
          <button v-for="i in 5" :key="i" class="rate-star" :class="{ on: (ratings[d.id] || 0) >= i }" :title="i + ' 分'" @click="rate(d, i)">
            {{ (ratings[d.id] || 0) >= i ? '★' : '☆' }}
          </button>
          <span v-if="ratings[d.id]" class="muted" style="font-size: 11px">{{ ratings[d.id] }} 分</span>
        </div>
      </div>
    </div>

    <n-modal
      v-model:show="showEdit"
      preset="card"
      :title="editing ? (editing.id ? '草稿 #' + editing.id : '新建草稿') : '草稿'"
      style="width: min(860px, 95vw)"
      :mask-closable="false"
      @close="closeEdit"
    >
      <div v-if="editing" style="max-height: 76vh; overflow-y: auto; padding-right: 6px">
        <n-tabs v-model:value="editTab" type="line" animated>
          <n-tab-pane name="edit" tab="编辑">
            <div class="form-grid">
              <div class="form-item">
                <label class="form-label">标题</label>
                <n-input v-model:value="editing.title" placeholder="视频标题" />
              </div>
              <div class="form-item">
                <label class="form-label">封面字</label>
                <n-input v-model:value="editing.cover_text" placeholder="与标题不同，3-8 字" />
              </div>
            </div>
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
                :rows="16"
                placeholder="在这里撰写 / 改写脚本"
              />
              <div v-else class="prose md-preview" v-html="renderMd(editing.script)" />
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
              <div v-else-if="isPending" class="empty" style="padding: 12px 0">模型讨论中，正在留痕…</div>
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
import { renderMd } from '../md'

const drafts = ref([])
const editing = ref(null)
const showEdit = ref(false)
const editTab = ref('edit')
const discussions = ref([])
const discussionsMap = ref({})
const debateStatus = ref('')
const preview = ref(false)
const scriptInput = ref(null)
const imgInput = ref(null)
const ratings = ref({})
const message = useMessage()
let pollTimer = null

const isPending = computed(() => {
  const s = editing.value?.script || ''
  return s.includes('双模型讨论生成中')
})

const STATUS_NAMES = { draft: '草稿', used: '已采用', archived: '已归档' }
const statusName = (s) => STATUS_NAMES[s] || s

function discussionCount(id) {
  return (discussionsMap.value[id] || []).length
}

function fmt(v) {
  return v ? v.replace('T', ' ').slice(0, 16) : ''
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
  drafts.value = await api('/api/drafts?limit=100')
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
  editing.value = { ...d }
  preview.value = false
  showEdit.value = true
  discussions.value = discussionsMap.value[d.id] || []
  if (!isNew && editing.value.id) location.hash = `#/drafts?id=${editing.value.id}`
  if (discussions.value.length) editTab.value = 'edit'
}

function openDiscussion(d) {
  editing.value = { ...d }
  showEdit.value = true
  editTab.value = 'discuss'
  discussions.value = discussionsMap.value[d.id] || []
  loadDiscussions(d.id)
}

function closeEdit() {
  showEdit.value = false
  editing.value = null
  debateStatus.value = ''
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
    script: editing.value.script
  }
  await api(`/api/drafts/${editing.value.id}`, { method: 'PATCH', body: JSON.stringify(body) })
  message.success('已保存（AI 原稿改写差异已进入人设学习）')
  closeEdit()
  load()
}

async function like(d, liked) {
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked }) })
  message.success(liked ? '已标记采用' : '已标记不用')
  load()
}

async function rate(d, i) {
  await api(`/api/drafts/${d.id}/feedback`, { method: 'POST', body: JSON.stringify({ liked: null, rating: i }) })
  ratings.value = { ...ratings.value, [d.id]: i }
  message.success(`已打 ${i} 分（进入人设/选题学习）`)
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
    /* 忽略轮询错误 */
  }
}

onMounted(async () => {
  await load()
  const m = location.hash.match(/id=(\d+)/)
  if (m) {
    const d = drafts.value.find(x => x.id === Number(m[1]))
    if (d) open(d)
  }
  pollTimer = setInterval(poll, 3000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
